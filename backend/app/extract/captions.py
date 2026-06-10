"""1A-V1 · Caption style + position detection (VLM main path).

Window strategy (二轮优化):
- Group sampled frames by scene_idx (frame_sampler already labels them).
- Each scene's frames form a *window*; windows >6 frames are chunked
  (the VLM context budget for image grids).
- One VLM call per window → list of raw caption rows + a call-level event.
- After every window has run, cross-window dedup by IoU + style +
  semantic_purpose → one merged ``Phase1ACaptionEvent`` per caption.
- Emit one entity event per merged caption, with ``parent_event_id``
  pointing at the call event that first detected it.

This replaces the previous single-call "first 6 frames" approach: a 7-sec
clip with 5 scenes used to silently drop captions after frame 6 (the
hidden ``[:6]`` cap), and any caption whose ``frames_appeared`` indices
exceeded the cap was filtered out by the anchor lookup. Both root causes
disappear with windowing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.ir.phase1a_report import Phase1ACaptionEvent
from app.ir.template import CaptionStyle
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import (
    AnthropicClient,
    FrameRef,
    OpenAICompatClient,
    chat_vision_dual,
    should_dual_check,
)
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "1A.captions"
log = get_logger(__name__)

# VLM image-grid budget per call. Empirically: 6 frames in a 2x3 grid still
# fits comfortably under Qwen-VL and Claude Sonnet 4.6 context limits.
_FRAMES_PER_WINDOW = 6


# ---------- VLM response schema (0-999 coords, raw VLM output) ----------


class _CaptionRaw(BaseModel):
    position_norm_0_999: list[int] = Field(default_factory=list)
    size_norm_0_999: list[int] = Field(default_factory=list)
    color_hex: str = "#FFFFFF"
    stroke_color_hex: str | None = None
    stroke_width_px: int = 0
    font_size_px_estimate: int = 56
    anim_in_type: str = "unknown"
    layout: str = "single"
    max_chars_per_line: int = 12
    placeholder_text: list[str] = Field(default_factory=list)
    length_constraint: dict[str, int] = Field(default_factory=dict)
    semantic_purpose: str = "regular"
    frames_appeared: list[int] = Field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


class CaptionsRawResult(BaseModel):
    captions: list[_CaptionRaw] = Field(default_factory=list)

    def __workbench_label__(self) -> str:
        return f"字幕识别 · {len(self.captions)} 条"


@dataclass
class _CaptionDraft:
    """Intermediate per-window detection awaiting cross-window merge.

    Carries the raw VLM row plus the resolved absolute timestamps + anchor
    frame so the post-merge entity emission has everything it needs without
    re-doing window-local index math.
    """

    raw: _CaptionRaw
    anchor: FrameSample
    ts_appeared: list[float]
    call_ev_id: str | None
    # Bbox in 0-999 normalized space, derived from raw position/size and
    # cached here so merge can compare without redoing the unpack.
    bbox: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))


# ---------- Public API ----------


async def detect_captions(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[list[Phase1ACaptionEvent], list[VisionEvent]]:
    """Run VLM caption detection over every scene window, then merge.

    Event ordering:
    1. One call event per window (no IR write).
    2. After all windows: one entity event per merged caption (IR append).

    The first call event's id is the parent_event_id of every entity event
    whose first observation came from that window; this preserves the
    "phase1 call → phase2 entity" causal chain for the workbench gantt
    view.
    """
    frames = await ctx.frames()
    if not frames:
        return [], []

    windows = _build_windows(frames)
    settings = get_settings()
    cl = ctx.client(STAGE)
    bus = get_event_bus()

    all_events: list[VisionEvent] = []
    drafts: list[_CaptionDraft] = []

    for win_idx, window in enumerate(windows):
        result, evs = await _call_window(
            cl,
            window,
            win_idx=win_idx,
            n_windows=len(windows),
            task_id=ctx.task_id,
            model=settings.model_vlm,
            parent_event_id=parent_event_id,
        )
        all_events.extend(evs)
        call_ev_id = evs[0].event_id if evs else parent_event_id
        for raw in result.captions:
            draft = _draft_from_raw(raw, window, call_ev_id)
            if draft is not None:
                drafts.append(draft)

    merged_drafts = _merge_drafts(drafts)

    out: list[Phase1ACaptionEvent] = []
    for draft in merged_drafts:
        entry = _to_caption_entry(draft)
        entity_ev = VisionEvent(
            task_id=ctx.task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            frame_ts=draft.anchor.ts,
            frame_url=f"/data/{draft.anchor.rel_path.lstrip('/')}",
            bbox_norm=tuple(float(v) for v in draft.bbox),
            # Entity event anchored to the caption's first observed frame.
            # Use that as media_ts; ts_appeared min/max could form a span,
            # but the entity card best plays back from where the caption
            # first appears (matches the bbox / frame_url anchoring).
            media_ts=float(draft.anchor.ts),
            semantic_label=f"画面字幕：{draft.raw.semantic_purpose} · {entry.style.layout}",
            reasoning=draft.raw.reasoning[:200],
            confidence=draft.raw.confidence,
            ir_target=IRTarget(ir_type="Phase1AReport", path="captions", op="append"),
            ir_value=entry.model_dump(mode="json"),
            parent_event_id=draft.call_ev_id,
            duration_ms=0,
        )
        await bus.publish(ctx.task_id, entity_ev)
        all_events.append(entity_ev)
        out.append(entry)

    return out, all_events


# ---------- Window construction ----------


def _build_windows(frames: Sequence[FrameSample]) -> list[list[FrameSample]]:
    """Split frames into VLM-callable windows.

    Grouping by ``scene_idx`` keeps each window stylistically homogeneous,
    which is what the prompt assumes. Scenes with >6 frames split into
    consecutive chunks of up to _FRAMES_PER_WINDOW. Frames missing scene
    info (rare — only if frame_sampler ran with no scenes) all collapse
    into a single chronological window list.
    """
    by_scene: dict[object, list[FrameSample]] = defaultdict(list)
    order: list[object] = []
    for f in frames:
        key = f.scene_idx if f.scene_idx is not None else "_unscened"
        if key not in by_scene:
            order.append(key)
        by_scene[key].append(f)

    windows: list[list[FrameSample]] = []
    for key in order:
        group = by_scene[key]
        # Preserve temporal order inside each scene.
        group.sort(key=lambda f: f.ts)
        for i in range(0, len(group), _FRAMES_PER_WINDOW):
            windows.append(group[i : i + _FRAMES_PER_WINDOW])
    return windows


async def _call_window(
    cl,
    window: list[FrameSample],
    *,
    win_idx: int,
    n_windows: int,
    task_id: str,
    model: str,
    parent_event_id: str | None,
) -> tuple[CaptionsRawResult, list[VisionEvent]]:
    """One VLM call covering ``window`` frames; returns (parsed, [call_event])."""
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in window]
    scene_label = (
        f"scene {window[0].scene_idx}" if window[0].scene_idx is not None else "全片"
    )
    user_prompt = (
        f"请按上述 schema 识别这些采样帧中的字幕。"
        f"本次为窗口 {win_idx + 1}/{n_windows}（{scene_label}），共 {len(window)} 帧，"
        f"采样时间戳依次为 {[round(f.ts, 2) for f in window]}（秒）。"
        f"frames_appeared 用 0-indexed 整数（0..{len(window) - 1}），对应上述时间戳数组的下标。"
        "若该窗口内没有字幕，返回 captions=[]；窗口间会自动合并跨窗口的同一字幕，不要重复列出多个窗口都能看到的字幕。"
    )
    messages = [
        {"role": "system", "content": load_prompt("1a_captions")},
        {"role": "user", "content": user_prompt},
    ]
    if should_dual_check(STAGE):
        primary, secondary = (
            (cl, AnthropicClient())
            if isinstance(cl, OpenAICompatClient)
            else (cl, OpenAICompatClient())
        )
        return await chat_vision_dual(
            primary=primary,
            secondary=secondary,
            messages=messages,
            model_primary=model,
            model_secondary="claude-sonnet-4-6",
            stage=STAGE,
            task_id=task_id,
            frames=frame_refs,
            ir_target_template=None,  # call-level event has no IR write
            schema=CaptionsRawResult,
            parent_event_id=parent_event_id,
        )
    return await cl.chat_vision(
        messages,
        model=model,
        stage=STAGE,
        task_id=task_id,
        frames=frame_refs,
        ir_target_template=None,
        schema=CaptionsRawResult,
        parent_event_id=parent_event_id,
    )


def _draft_from_raw(
    raw: _CaptionRaw, window: list[FrameSample], call_ev_id: str | None
) -> _CaptionDraft | None:
    """Build a _CaptionDraft from a single raw VLM row.

    Returns None when the row is unusable:
    - ``frames_appeared`` empty (model didn't ground the caption in any frame)
    - all ``frames_appeared`` indices are out of window range (model lied)
    """
    if not raw.frames_appeared:
        return None
    valid = [i for i in raw.frames_appeared if 0 <= i < len(window)]
    if not valid:
        return None
    anchor = window[valid[0]]
    ts_appeared = [window[i].ts for i in valid]
    bbox = _bbox_from_pos_size(raw.position_norm_0_999, raw.size_norm_0_999)
    return _CaptionDraft(
        raw=raw,
        anchor=anchor,
        ts_appeared=ts_appeared,
        call_ev_id=call_ev_id,
        bbox=bbox,
    )


# ---------- Cross-window merge ----------


def _merge_drafts(drafts: list[_CaptionDraft]) -> list[_CaptionDraft]:
    """Merge same-caption drafts surfaced by different windows.

    Match rule: same ``semantic_purpose`` AND bbox IoU > 0.5. Time-adjacent
    sightings of the same caption (same scene + same style + slid forward
    in time) win this match and consolidate.

    On match: union ``ts_appeared``, keep the earliest anchor (so the
    workbench plays back the *first* sighting), and keep the
    highest-confidence raw's textual fields (placeholder/reasoning).
    """
    merged: list[_CaptionDraft] = []
    for d in drafts:
        target: _CaptionDraft | None = None
        for m in merged:
            if (
                d.raw.semantic_purpose == m.raw.semantic_purpose
                and _iou(list(d.bbox), list(m.bbox)) > 0.5
            ):
                target = m
                break
        if target is None:
            merged.append(d)
            continue
        target.ts_appeared = sorted(set(target.ts_appeared) | set(d.ts_appeared))
        if d.anchor.ts < target.anchor.ts:
            target.anchor = d.anchor
            target.call_ev_id = d.call_ev_id  # follow the earliest sighting's call
        if d.raw.confidence > target.raw.confidence:
            # Adopt the more confident row's textual fields without losing
            # the established temporal extent.
            new_raw = d.raw.model_copy()
            new_raw.frames_appeared = target.raw.frames_appeared  # kept for parity
            target.raw = new_raw
            target.bbox = d.bbox
    return merged


def _to_caption_entry(draft: _CaptionDraft) -> Phase1ACaptionEvent:
    style = _to_caption_style(draft.raw, draft.bbox)
    return Phase1ACaptionEvent(
        style=style,
        start=min(draft.ts_appeared),
        end=max(draft.ts_appeared) + 0.5,  # tail buffer
        placeholder_text=draft.raw.placeholder_text,
        length_constraint=draft.raw.length_constraint,
        semantic_purpose=draft.raw.semantic_purpose,
        bbox_norm_0_999=draft.bbox,
        frames_appeared=draft.ts_appeared,
        confidence=draft.raw.confidence,
        reasoning=draft.raw.reasoning[:200],
    )


# ---------- helpers ----------


def _iou(a: list[int], b: list[int]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _bbox_from_pos_size(pos: list[int], size: list[int]) -> tuple[int, int, int, int]:
    if len(pos) >= 4:
        return tuple(pos[:4])  # type: ignore[return-value]
    if len(pos) >= 2 and len(size) >= 2:
        return (pos[0], pos[1], size[0], size[1])
    return (0, 0, 0, 0)


def _to_caption_style(cap: _CaptionRaw, bbox: tuple[int, int, int, int]) -> CaptionStyle:
    cx = (bbox[0] + bbox[2] / 2) / 1000.0
    cy = (bbox[1] + bbox[3] / 2) / 1000.0
    return CaptionStyle(
        size=cap.font_size_px_estimate,
        color=cap.color_hex,
        stroke_color=cap.stroke_color_hex,
        stroke_width=cap.stroke_width_px,
        position=(round(cx, 4), round(cy, 4)),
        layout=cap.layout if cap.layout in ("single", "multi") else "single",
        max_chars_per_line=cap.max_chars_per_line,
        anim_in=cap.anim_in_type,
    )


# ---------- legacy alias (back-compat for callers that import the dataclass) ----------

# The pre-二核 implementation exposed ``CaptionEvent`` (a dataclass) as the
# return-type of detect_captions; downstream code (the lab runner,
# integration tests) imports it. Map the alias to the new pydantic IR
# model so existing imports keep working without ABC churn.
CaptionEvent = Phase1ACaptionEvent

__all__ = [
    "CaptionEvent",
    "CaptionsRawResult",
    "Phase1ACaptionEvent",
    "STAGE",
    "detect_captions",
]


def _scene_anchor_frames(frames: Sequence[FrameSample]) -> list[FrameSample]:
    """Used by older imports — returns frames unchanged. Kept as a no-op."""
    return list(frames)
