"""2.style · apply slot StyleRule to PlacedSegments + emit Caption list (PLAN 1602-1608).

Three sub-steps:

1. **Apply per-slot StyleRule onto PlacedSegments**: each PlacedSegment
   inherits its slot's caption / zoom / stickers / transitions /
   color_lut. We deep-copy so later NL edits to a single segment don't
   leak back into the template KB row.
2. **Build Caption list**: for each PlacedSegment we walk its
   ``source_unit_ids`` and emit one Caption per Unit (text=Unit.text,
   start/end mapped to timeline via PlacedSegment's
   ``timeline_start`` + ``speed``). The Caption's ``style`` copies the
   slot's CaptionStyle, with ``emphasis_words`` selected by a Text LLM
   call against the slot's placeholder anchors (PLAN 1604).
3. **BGM selection**: picks ``bgm_track`` per ``BGM_STRATEGY``:
   - ``features``: nearest BGM in ``data/system/bgm_pool/bgm_index.json``
     by Euclidean distance on (BPM, mood_tag dummy).
   - ``original``: uses the template's ``ir.audio.bgm_path`` directly.

D11 hard rule: Caption.text == Unit.text always. The LLM call only chooses
``emphasis_words``; no rewriting / truncation.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger, Unit
from app.ir.project import Caption, PlacedSegment
from app.ir.template import AudioStyle, CaptionStyle, Slot, StyleRule, TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import get_llm_client
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "2.style"
log = get_logger(__name__)


class _EmphasisResult(BaseModel):
    emphasis_words: list[str] = Field(default_factory=list)
    reasoning: str = ""


def _segment_output_span(seg: PlacedSegment) -> float:
    """Renderable output span: ``(src_end - src_start) / speed``.

    Single source of truth used by mapping (timeline_cursor advance),
    fill (cursor reconstruction), style (sticker remapping), and the
    renderers (durationInFrames). The expression must stay identical
    everywhere — diverging caused the Phase 2 timeline drift bug.
    """
    src_start, src_end = seg.src_timerange
    return max(0.0, src_end - src_start) / max(0.04, seg.speed)


def style_for_segment(slot: Slot, output_span: float) -> StyleRule:
    """Deep-copy ``slot.style`` and remap stickers to segment-local seconds.

    Slot stickers carry slot-local fractional timing in [0,1] (set by
    ``extract/skeleton.py:_stickers_in``). Phase 2 segments have their
    own ``output_span`` derived from src_timerange + speed; we project
    [0,1] onto that span. Result: ``applied_style.stickers[*].start/end``
    are plain segment-local seconds the renderer can consume.
    """
    rule = slot.style.model_copy(deep=True)
    rule.stickers = [
        s.model_copy(
            update={
                "start": round(max(0.0, min(1.0, s.start)) * output_span, 3),
                "end": round(max(0.0, min(1.0, s.end)) * output_span, 3),
            }
        )
        for s in rule.stickers
    ]
    return rule


async def _emphasis_for_unit(
    unit: Unit,
    cap_style: CaptionStyle,
    *,
    task_id: str,
    parent_event_id: str | None,
) -> tuple[list[str], str]:
    """LLM picks 0-3 emphasis words from Unit.text using placeholder anchors.

    Returns ``([], "")`` when the slot has no caption style (caller should
    not have invoked us in that case but we defend).
    """
    settings = get_settings()
    cl = get_llm_client(stage=f"{STAGE}.caption")

    system = load_prompt("2_caption_emphasis")
    user_msg = (
        f"unit_text: {unit.text}\n"
        f"placeholder_text: {list(cap_style.placeholder_text)}\n"
        f"length_constraint: {dict(cap_style.length_constraint)}\n"
        f"semantic_purpose: {cap_style.semantic_purpose}\n"
        "请按 schema 输出 emphasis_words + reasoning JSON。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    result, _events = await cl.chat_text(
        messages,
        model=settings.model_text_cheap,
        stage=f"{STAGE}.caption",
        task_id=task_id,
        ir_target_template=IRTarget(
            ir_type="ProjectIR", path="captions", op="append"
        ),
        schema=_EmphasisResult,
        parent_event_id=parent_event_id,
    )
    # Enforce the "substring of unit_text" hard rule from the prompt; drop
    # any LLM-invented word that doesn't actually appear so the renderer's
    # highlight match doesn't silently fail.
    surviving = [w for w in result.emphasis_words if w and w in unit.text]
    return surviving[:3], result.reasoning or ""


def _timeline_range_for_unit(unit: Unit, seg: PlacedSegment) -> tuple[float, float]:
    """Map a Unit's source time range onto the timeline via the segment's speed.

    src_offset_in_seg = unit.start - seg.src_timerange[0]
    timeline_start = seg.timeline_start + src_offset_in_seg / seg.speed
    """
    src_start, src_end = seg.src_timerange
    speed = max(0.04, seg.speed)
    rel_start = max(0.0, unit.start - src_start)
    rel_end = max(rel_start + 0.04, unit.end - src_start)
    return (
        round(seg.timeline_start + rel_start / speed, 3),
        round(seg.timeline_start + rel_end / speed, 3),
    )


async def apply_style(
    segments: list[PlacedSegment],
    template: TemplateIR,
    ledger: TranscriptLedger,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[list[PlacedSegment], list[Caption], str | None, list[VisionEvent]]:
    """Apply slot StyleRule + emit per-Unit Captions + select BGM.

    Returns ``(segments_with_style, captions, bgm_track, events)``.

    Failure modes:
    - LLM emphasis call falls back internally via ``_invoke``'s warning path;
      the affected Caption gets ``emphasis_words=[]`` and a warning event.
    - BGM selection failure (missing index, missing pool) returns
      ``bgm_track=None`` and emits a warning so the renderer skips the
      ``<Audio>`` track gracefully.
    """
    started = time.perf_counter()
    bus = get_event_bus()
    events: list[VisionEvent] = []

    # ----- Step 1: per-segment style apply --------------------------------
    skeleton_by_role_pos: dict[tuple[str, int], int] = {}
    role_counter: dict[str, int] = {}
    for i, slot in enumerate(template.skeleton):
        pos = role_counter.get(slot.role, 0)
        skeleton_by_role_pos[(slot.role, pos)] = i
        role_counter[slot.role] = pos + 1

    role_walk: dict[str, int] = {}
    styled: list[PlacedSegment] = []
    seg_slot_idx: list[int | None] = []
    for seg in segments:
        pos = role_walk.get(seg.slot_role, 0)
        role_walk[seg.slot_role] = pos + 1
        slot_idx = skeleton_by_role_pos.get((seg.slot_role, pos))
        if slot_idx is None:
            styled.append(seg)
            seg_slot_idx.append(None)
            continue
        slot = template.skeleton[slot_idx]
        output_span = _segment_output_span(seg)
        applied = style_for_segment(slot, output_span)
        # Apply to mapped (non-fill) segments and to fill segments that
        # somehow still carry default StyleRule (defensive — fill.py
        # already copies via the same helper).
        if not seg.is_fill or seg.applied_style.model_dump() == StyleRule().model_dump():
            seg = seg.model_copy(update={"applied_style": applied})
        styled.append(seg)
        seg_slot_idx.append(slot_idx)
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.segment",
            semantic_label=f"套风格 segment#{len(styled) - 1} · slot#{slot_idx} · {seg.slot_role}",
            reasoning=(
                f"slot#{slot_idx} 的 StyleRule (caption / zoom_keyframes "
                f"{len(slot.style.visual.zoom_keyframes)} / stickers "
                f"{len(slot.style.stickers)} / mask={slot.style.visual.mask}) "
                f"深拷贝到 PlacedSegment.applied_style；stickers 时间 "
                f"[0,1] → 0–{output_span:.2f}s（segment-local）。"
            ),
            confidence=1.0,
            ir_target=IRTarget(
                ir_type="ProjectIR",
                path=f"sections.0.segments.{len(styled) - 1}.applied_style",
            ),
            ir_value=seg.applied_style.model_dump(mode="json"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)

    # ----- Step 2: Caption list per Unit ----------------------------------
    captions: list[Caption] = []
    units_by_id: dict[int, Unit] = {u.id: u for u in ledger.units}
    for seg_idx, seg in enumerate(styled):
        slot_idx = seg_slot_idx[seg_idx]
        if slot_idx is None:
            continue
        slot = template.skeleton[slot_idx]
        cap_style = slot.style.caption
        if cap_style is None or not seg.source_unit_ids or seg.is_fill:
            continue
        for unit_id in seg.source_unit_ids:
            unit = units_by_id.get(unit_id)
            if unit is None:
                continue
            tl_start, tl_end = _timeline_range_for_unit(unit, seg)
            emphasis_words, reasoning = await _emphasis_for_unit(
                unit,
                cap_style,
                task_id=task_id,
                parent_event_id=parent_event_id,
            )
            cap = Caption(
                text=unit.text,
                start=tl_start,
                end=tl_end,
                style=cap_style.model_copy(
                    update={"emphasis_words": emphasis_words}, deep=True
                ),
            )
            captions.append(cap)
            ev = VisionEvent(
                task_id=task_id,
                source="text_llm",
                stage=f"{STAGE}.caption",
                semantic_label=(
                    f"字幕 #{len(captions) - 1} · Unit#{unit.id} · "
                    f"emphasis={emphasis_words or '∅'}"
                ),
                reasoning=(
                    f"text='{unit.text}'；placeholder={list(cap_style.placeholder_text)[:1]}；"
                    f"LLM 选取 emphasis_words={emphasis_words}。{reasoning}"
                ),
                confidence=0.85,
                ir_target=IRTarget(ir_type="ProjectIR", path="captions", op="append"),
                ir_value=cap.model_dump(mode="json"),
                parent_event_id=parent_event_id,
            )
            await bus.publish(task_id, ev)
            events.append(ev)

    # ----- Step 3: BGM selection ------------------------------------------
    bgm_track = await _select_bgm(
        template=template,
        task_id=task_id,
        parent_event_id=parent_event_id,
        events=events,
    )

    elapsed = int((time.perf_counter() - started) * 1000)
    ev = VisionEvent(
        task_id=task_id,
        source="system",
        stage=f"{STAGE}.done",
        semantic_label=(
            f"风格应用完成 · {len(styled)} 段 · {len(captions)} 条字幕 · "
            f"BGM={'有' if bgm_track else '无'}"
        ),
        reasoning=f"耗时 {elapsed}ms",
        confidence=1.0,
        ir_target=IRTarget(ir_type="ProjectIR", path="captions"),
        ir_value=[c.model_dump(mode="json") for c in captions],
        parent_event_id=parent_event_id,
        duration_ms=elapsed,
    )
    await bus.publish(task_id, ev)
    events.append(ev)

    return styled, captions, bgm_track, events


# ---------------------------------------------------------------------------
# BGM selection helpers
# ---------------------------------------------------------------------------


async def _select_bgm(
    *,
    template: TemplateIR,
    task_id: str,
    parent_event_id: str | None,
    events: list[VisionEvent],
) -> str | None:
    """Pick a BGM track per BGM_STRATEGY. Returns DATA_ROOT-relative path or None."""
    settings = get_settings()
    bus = get_event_bus()
    audio = template.audio
    if audio is None or not audio.has_bgm:
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.bgm.skip",
            semantic_label="无 BGM · 模板未声明 has_bgm",
            reasoning="template.audio is None or has_bgm=false；ProjectIR.bgm_track 留空。",
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
            ir_value=None,
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
        return None

    strategy = settings.bgm_strategy
    if strategy == "original":
        return await _bgm_original(audio, task_id, parent_event_id, events)
    return await _bgm_features(audio, task_id, parent_event_id, events)


async def _bgm_original(
    audio: AudioStyle,
    task_id: str,
    parent_event_id: str | None,
    events: list[VisionEvent],
) -> str | None:
    bus = get_event_bus()
    path = audio.bgm_path
    if not path:
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.bgm.original_missing",
            semantic_label="[warning] BGM_STRATEGY=original 但 template.audio.bgm_path 为空",
            reasoning="无可用 BGM；ProjectIR.bgm_track 留空。",
            confidence=0.0,
            severity="warning",
            ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
        return None
    ev = VisionEvent(
        task_id=task_id,
        source="system",
        stage=f"{STAGE}.bgm.original",
        semantic_label=f"BGM · 直接复用模板原曲 · {Path(path).name}",
        reasoning=f"BGM_STRATEGY=original；返回 template.audio.bgm_path={path}。",
        confidence=1.0,
        ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
        ir_value=path,
        parent_event_id=parent_event_id,
    )
    await bus.publish(task_id, ev)
    events.append(ev)
    return path


async def _bgm_features(
    audio: AudioStyle,
    task_id: str,
    parent_event_id: str | None,
    events: list[VisionEvent],
) -> str | None:
    """Nearest neighbour in bgm_index.json by (BPM, mood) feature distance."""
    bus = get_event_bus()
    settings = get_settings()
    index_path = settings.data_root / "system" / "bgm_pool" / "bgm_index.json"
    if not index_path.exists():
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.bgm.features_missing",
            semantic_label="[warning] BGM 索引缺失 · bgm_index.json 不存在",
            reasoning=(
                f"BGM_STRATEGY=features 但 {index_path} 不存在；ProjectIR.bgm_track 留空。"
                "请准备至少 5 首曲目 + bgm_index.json (PLAN 1578)。"
            ),
            confidence=0.0,
            severity="warning",
            ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
        return None
    try:
        catalog = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.bgm.features_parse_failed",
            semantic_label="[warning] BGM 索引解析失败",
            reasoning=f"{type(e).__name__}: {e}",
            confidence=0.0,
            severity="warning",
            ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
        return None

    tracks = catalog.get("tracks") or []
    if not tracks:
        return None

    template_bpm = float(audio.bpm or 100.0)
    template_mood = (audio.mood_tag or "neutral").strip()

    def _feature_distance(track: dict) -> float:
        bpm = float(track.get("bpm", 100.0))
        mood = (track.get("mood_tag", "") or "").strip()
        bpm_d = abs(bpm - template_bpm) / 100.0
        mood_d = 0.0 if mood == template_mood else 1.0
        return math.sqrt(bpm_d**2 + mood_d**2)

    best = min(tracks, key=_feature_distance)
    path = best.get("path") or ""
    if not path:
        return None

    ev = VisionEvent(
        task_id=task_id,
        source="system",
        stage=f"{STAGE}.bgm.features",
        semantic_label=f"BGM · features 策略匹配 · {best.get('name', path)}",
        reasoning=(
            f"BGM_STRATEGY=features；template_bpm={template_bpm:.0f} mood={template_mood}；"
            f"匹配 {best.get('name', path)} (bpm={best.get('bpm')} mood={best.get('mood_tag')})。"
        ),
        confidence=0.85,
        ir_target=IRTarget(ir_type="ProjectIR", path="bgm_track"),
        ir_value=path,
        parent_event_id=parent_event_id,
    )
    await bus.publish(task_id, ev)
    events.append(ev)
    return path


__all__ = ["STAGE", "apply_style", "style_for_segment"]
