"""2.fill · gap completion (PLAN 1601).

Four strategies:

1. **text_fill**: Text LLM generates a Caption for the gap, anchored by the
   slot's caption ``placeholder_text`` + ``length_constraint`` +
   ``semantic_purpose``. The fill text is marked ``is_fill=True`` on the
   produced PlacedSegment so workbench / Editor can flag it for user review.
2. **wrap_fill** (packaging fill): No text; the gap becomes a
   "styling-only" PlacedSegment that reuses the nearest user-material
   frame as background and overlays the slot's sticker placeholders.
   StyleRule colors fill from the slot's existing visual style.
3. **reuse**: Take an adjacent PlacedSegment's last 0.5-1.0s, zoom-in,
   and repeat it. No text added; no LLM call.
4. **aigc_broll** (Phase 5, ISS-028): the slot's ``material_req`` is
   "AI生成画面". When ``allow_aigc_broll`` is True we synthesize an image
   prompt from the slot's ASR context + template tags and call
   ``agent.aigc.generate_broll`` to fetch a third-party text-to-image then
   loop it into mp4 via ffmpeg, writing the result onto
   ``PlacedSegment.aigc_broll_path`` + ``use_aigc_broll``.
   Any ``AIGCProviderError`` (missing key / quota / network / content
   rejected) degrades the slot to ``reuse`` and records the reason in the
   outcome's ``degraded_msg`` so the pipeline can flag
   ``ProjectIR.degraded`` (D28 — never block the pipeline). When the
   project did **not** opt in, the slot degrades straight to ``reuse``
   without touching the AIGC provider (D10 — user-initiated only).

Each fill emits one VisionEvent so the workbench shows the completed
gap card filling in.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.aigc import AIGCProviderError, generate_broll
from app.apply.style import _segment_output_span, style_for_segment
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger
from app.ir.project import Caption, Gap, PlacedSegment
from app.ir.template import Slot, TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import get_llm_client
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "2.fill"
log = get_logger(__name__)


class _FillTextResult(BaseModel):
    text: str = ""
    reasoning: str = ""


class _BrollPromptResult(BaseModel):
    """LLM-synthesized image prompt for an AI生成画面 slot (5_aigc_broll.md).

    The renderer's ZoomLayer supplies motion at render time, so the prompt
    describes a *still* composition; the LLM is told not to use motion verbs.
    """

    prompt: str = ""
    style_keywords: list[str] = Field(default_factory=list)
    reasoning: str = ""


class FillOutcome(BaseModel):
    """Result of filling one Gap. Drives ProjectIR insertion."""

    gap_idx: int
    strategy: str
    text: str = ""  # for text_fill / wrap_fill captions
    segment: PlacedSegment | None = None  # generated styling-only segment
    caption: Caption | None = None  # generated caption (if any)
    reasoning: str = ""
    # Set when an AIGC B-roll attempt failed and degraded to reuse. The
    # pipeline reads this to write ``ProjectIR.degraded[sections.0.segments.
    # {i}.aigc_broll]`` against the final (post-sort) segment index, so the
    # workbench banner can navigate to the affected segment.
    degraded_msg: str = ""


def _ctx_units(
    ledger: TranscriptLedger,
    *,
    before: int = 2,
    after: int = 2,
    pivot_unit_id: int | None = None,
) -> tuple[str, str]:
    """Return ``(before_text, after_text)`` for fill_gap LLM context.

    Centred on ``pivot_unit_id`` when supplied; otherwise we collapse to
    "entire ledger as before, empty as after" (open-ended gap at end).
    """
    if pivot_unit_id is None:
        head = "".join(u.text for u in ledger.units[-before:])
        return head, ""
    units = ledger.units
    if pivot_unit_id < 0 or pivot_unit_id >= len(units):
        return "", ""
    before_text = "".join(u.text for u in units[max(0, pivot_unit_id - before) : pivot_unit_id])
    after_text = "".join(u.text for u in units[pivot_unit_id + 1 : pivot_unit_id + 1 + after])
    return before_text, after_text


def _pivot_unit_for(
    segments: list[PlacedSegment], ledger: TranscriptLedger
) -> int | None:
    """Pick a "pivot" Unit id approximating where a trailing gap sits.

    Strategy: find the segment that immediately precedes the gap by
    timeline_start; use its last source_unit_id. None when no segments
    exist (mapping returned []).
    """
    if not segments or not ledger.units:
        return None
    # Sort segments by timeline_start and take the last one with
    # source_unit_ids — for trailing gaps this is the closest preceding
    # voice anchor for LLM context.
    sorted_segs = sorted(segments, key=lambda s: s.timeline_start)
    for seg in reversed(sorted_segs):
        if seg.source_unit_ids:
            return seg.source_unit_ids[-1]
    return None


async def _fill_text(
    gap: Gap,
    slot: Slot,
    *,
    ledger: TranscriptLedger,
    segments: list[PlacedSegment],
    template: TemplateIR,
    task_id: str,
    parent_event_id: str | None,
) -> tuple[str, str]:
    """LLM-driven caption text. Returns ``(text, reasoning)``."""
    settings = get_settings()
    cl = get_llm_client(stage=f"{STAGE}.text")

    cap_style = template.get_slot_caption(slot)
    placeholder = list(cap_style.placeholder_text) if cap_style else []
    length_constraint = dict(cap_style.length_constraint) if cap_style else {}
    semantic_purpose = cap_style.semantic_purpose if cap_style else "regular"

    pivot = _pivot_unit_for(segments, ledger)
    before_txt, after_txt = _ctx_units(ledger, pivot_unit_id=pivot)

    system = load_prompt("2_fill_gap")
    user_msg = (
        f"slot_role: {slot.role}\n"
        f"material_req: {slot.material_req}\n"
        f"placeholder_text: {placeholder}\n"
        f"length_constraint: {length_constraint}\n"
        f"semantic_purpose: {semantic_purpose}\n"
        f"context_before: {before_txt or '（无）'}\n"
        f"context_after: {after_txt or '（无）'}\n"
        f"tags: {template.tags.model_dump()}\n"
        "请按 schema 输出补全文案 JSON。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    result, _events = await cl.chat_text(
        messages,
        model=settings.model_text_cheap,
        stage=f"{STAGE}.text",
        task_id=task_id,
        ir_target_template=IRTarget(ir_type="ProjectIR", path="sections.0.gaps"),
        schema=_FillTextResult,
        parent_event_id=parent_event_id,
    )
    # If the model returned empty / oversize text, fall back to placeholder
    # (better something than nothing — the renderer needs a string).
    text = (result.text or "").strip()
    if not text and placeholder:
        text = placeholder[0]
    elif not text:
        text = "（补全占位）"
    max_chars = int(length_constraint.get("max_chars", 0) or 0)
    if max_chars > 0 and len(text) > max_chars * 1.5:
        # Soft over-budget guard. We don't truncate aggressively (the LLM
        # was supposed to obey the constraint); just log it.
        log.warning(
            "fill.text_over_budget",
            text_len=len(text),
            max_chars=max_chars,
            slot_role=slot.role,
        )
    return text, result.reasoning or ""


def _wrap_segment_for(
    slot: Slot,
    timeline_start: float,
    nearest_src_range: tuple[float, float] | None,
) -> PlacedSegment:
    """Build a styling-only segment that reuses adjacent user-material frames.

    Output span MUST equal ``slot.duration.nominal`` so the timeline cursor
    stays aligned with what mapping reserved for this slot (mapping advanced
    its cursor by ``slot.nominal`` when it left this slot empty). We achieve
    that by picking a source slice and computing the speed so that
    ``src_span / speed = nominal``. Fill segments don't need to obey the
    ±20% speech-speed clamp because no spoken voice plays in them.

    ``applied_style`` is built via :func:`style_for_segment` so the slot's
    [0,1]-keyed stickers get remapped to segment-local seconds (output_span
    = nominal).
    """
    nominal = float(slot.duration.get("nominal", 1.5))
    if nearest_src_range is None:
        # No adjacent material — take the slot's nominal slice from the
        # start of the user clip. Loops cleanly via OffthreadVideo's clip
        # endpoints.
        src_span = max(0.5, nominal)
        src = (0.0, src_span)
        speed = src_span / nominal
    else:
        # Take up to the last 1.5s of nearest material; let speed stretch
        # it to slot.nominal so output_span lines up exactly.
        last = nearest_src_range[1]
        first = max(0.0, last - min(1.5, max(0.5, nominal)))
        src = (first, last)
        src_span = max(0.04, src[1] - src[0])
        speed = src_span / nominal
    return PlacedSegment(
        slot_role=slot.role,
        source_unit_ids=[],
        src_timerange=(round(src[0], 3), round(src[1], 3)),
        timeline_start=round(timeline_start, 3),
        speed=round(max(0.1, speed), 3),
        applied_style=style_for_segment(slot, nominal),
        is_fill=True,
    )


def _reuse_segment_for(
    slot: Slot,
    timeline_start: float,
    nearest_src_range: tuple[float, float] | None,
) -> PlacedSegment:
    """Same time-alignment contract as :func:`_wrap_segment_for` —
    output span must equal slot.nominal so the timeline stays continuous.
    The visual intent is "slow-motion repeat of the last beat".
    """
    nominal = float(slot.duration.get("nominal", 1.5))
    if nearest_src_range is None:
        src = (0.0, max(0.5, nominal))
    else:
        last = nearest_src_range[1]
        src = (max(0.0, last - 1.0), last)
    src_span = max(0.04, src[1] - src[0])
    speed = src_span / nominal
    return PlacedSegment(
        slot_role=slot.role,
        source_unit_ids=[],
        src_timerange=(round(src[0], 3), round(src[1], 3)),
        timeline_start=round(timeline_start, 3),
        speed=round(max(0.1, speed), 3),
        applied_style=style_for_segment(slot, nominal),
        is_fill=True,
    )


async def _synthesize_broll_prompt(
    slot: Slot,
    *,
    ledger: TranscriptLedger,
    segments: list[PlacedSegment],
    template: TemplateIR,
    duration_sec: float,
    task_id: str,
    parent_event_id: str | None,
) -> _BrollPromptResult:
    """Text LLM turns ASR context + template tags into an English image prompt.

    Falls back to a deterministic prompt built from the template scene tag
    when the LLM declines (``_invoke`` returns a default-constructed schema
    with empty ``prompt``) — generate_broll still needs a non-empty string.
    The fallback intentionally avoids motion language so it composes the
    same way as a real LLM-produced prompt with the renderer's ZoomLayer.
    """
    settings = get_settings()
    cl = get_llm_client(stage=f"{STAGE}.aigc_broll")

    pivot = _pivot_unit_for(segments, ledger)
    before_txt, after_txt = _ctx_units(ledger, pivot_unit_id=pivot)
    tags = template.tags

    system = load_prompt("5_aigc_broll")
    user_msg = (
        f"material_req: {slot.material_req}\n"
        f"scene: {tags.scene}\n"
        f"function: {tags.function}\n"
        f"duration_sec: {duration_sec:.1f}\n"
        f"content_before: {before_txt or '（无）'}\n"
        f"content_after: {after_txt or '（无）'}\n"
        "请按 schema 输出 image prompt JSON。"
    )
    result, _events = await cl.chat_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        model=settings.model_text_cheap,
        stage=f"{STAGE}.aigc_broll",
        task_id=task_id,
        ir_target_template=IRTarget(ir_type="ProjectIR", path="sections.0.segments"),
        schema=_BrollPromptResult,
        parent_event_id=parent_event_id,
    )
    if not (result.prompt or "").strip():
        # Deterministic fallback so generate_broll always gets a real prompt.
        # No motion verbs — the renderer's ZoomLayer supplies the motion.
        scene = tags.scene or "clean studio"
        result = _BrollPromptResult(
            prompt=(
                f"a still cinematic B-roll establishing composition, {scene} style, "
                "soft natural lighting, no text, no faces, no logos"
            ),
            style_keywords=[scene],
            reasoning="LLM 未给出 prompt，回退到基于模板 scene 标签的确定性静态构图 prompt。",
        )
    return result


async def _fill_aigc_broll(
    slot: Slot,
    timeline_start: float,
    nearest_src_range: tuple[float, float] | None,
    *,
    ledger: TranscriptLedger,
    segments: list[PlacedSegment],
    template: TemplateIR,
    project_id: str,
    task_id: str,
    parent_event_id: str | None,
) -> tuple[PlacedSegment, str, str]:
    """Generate an AI B-roll clip for an "AI生成画面" slot.

    Returns ``(segment, reasoning, degraded_msg)``. On success the segment
    carries ``aigc_broll_path`` + ``use_aigc_broll=True`` (and ``degraded_msg``
    is empty). On any ``AIGCProviderError`` we fall back to a ``reuse`` segment
    and return the failure in ``degraded_msg`` so the pipeline flags
    ``ProjectIR.degraded`` — the slot still renders (D28), just from adjacent
    user material instead of AI B-roll.

    The output span equals ``slot.nominal`` like every other fill segment so
    the timeline stays continuous; the AIGC clip's own duration is clamped by
    ``generate_broll`` to ``aigc_broll_max_duration_sec`` and looped/trimmed by
    the renderer's OffthreadVideo endpoints to fill the slot.
    """
    settings = get_settings()
    nominal = float(slot.duration.get("nominal", 1.5))
    duration = min(nominal, float(settings.aigc_broll_max_duration_sec))

    prompt_res = await _synthesize_broll_prompt(
        slot,
        ledger=ledger,
        segments=segments,
        template=template,
        duration_sec=duration,
        task_id=task_id,
        parent_event_id=parent_event_id,
    )
    style_hint = {
        "style_keywords": prompt_res.style_keywords,
        "scene": template.tags.scene,
        "function": template.tags.function,
    }
    try:
        rel_path, _events = await generate_broll(
            prompt_res.prompt,
            duration,
            style_hint,
            project_id,
            task_id=task_id,
            parent_event_id=parent_event_id,
        )
    except AIGCProviderError as e:
        degraded_msg = f"{type(e).__name__}: {e}"
        log.warning("fill.aigc_broll_degraded_to_reuse", slot_role=slot.role, error=str(e))
        seg = _reuse_segment_for(slot, timeline_start, nearest_src_range)
        reasoning = (
            f"AI 补画面失败（{degraded_msg}），降级到 reuse 策略："
            "裁取相邻片段重复填入；ProjectIR.degraded 已记录原因。"
        )
        return seg, reasoning, degraded_msg

    # Success — build a segment whose source plays the AIGC clip. We still
    # set src_timerange/speed so _segment_output_span keeps the timeline
    # contiguous; the renderer reads aigc_broll_path as the video source.
    seg = PlacedSegment(
        slot_role=slot.role,
        source_unit_ids=[],
        src_timerange=(0.0, round(max(0.04, duration), 3)),
        timeline_start=round(timeline_start, 3),
        speed=round(max(0.1, duration / nominal), 3),
        applied_style=style_for_segment(slot, nominal),
        is_fill=True,
        use_aigc_broll=True,
        aigc_broll_path=rel_path,
    )
    reasoning = (
        f"AI 补画面成功：prompt='{prompt_res.prompt[:60]}…'；"
        f"{prompt_res.reasoning}；资源 {rel_path}。"
    )
    return seg, reasoning, ""


async def fill_gaps(
    gaps: list[Gap],
    template: TemplateIR,
    segments: list[PlacedSegment],
    ledger: TranscriptLedger,
    *,
    task_id: str,
    project_id: str = "",
    allow_aigc_broll: bool = False,
    parent_event_id: str | None = None,
) -> tuple[list[FillOutcome], list[VisionEvent]]:
    """Fill each gap per its ``fill_strategy``.

    ``allow_aigc_broll`` gates the ``aigc_broll`` strategy (D10 — AIGC only
    runs when the user opted in). When False, "AI生成画面" slots degrade to
    ``reuse`` without touching the provider. The function never raises —
    AIGC provider failures degrade individual slots to reuse and are flagged
    via ``FillOutcome.degraded_msg`` for the pipeline to record; other
    failures inside one fill keep filling the rest.
    """
    bus = get_event_bus()
    outcomes: list[FillOutcome] = []
    events: list[VisionEvent] = []
    # Pre-build a slot_idx → slot map ordered the same as gaps. gaps were
    # emitted by detect_gaps in skeleton order, so we walk the skeleton
    # and match gaps positionally (no slot_idx field on Gap to avoid
    # making the IR carry implementation detail).
    skeleton = template.skeleton
    gap_iter = iter(enumerate(gaps))
    cur_gap_idx, cur_gap = next(gap_iter, (None, None))

    # Track the running timeline cursor so each fill segment lands after
    # the prior PlacedSegment. We re-walk the skeleton to reconstruct
    # contiguous time ordering.
    timeline_cursor = 0.0
    # For "nearest src range" reuse, keep the latest non-fill src_range.
    last_real_src: tuple[float, float] | None = None
    seg_by_role_pos: dict[tuple[str, int], PlacedSegment] = {}
    role_seen: dict[str, int] = {}
    for seg in segments:
        pos = role_seen.get(seg.slot_role, 0)
        seg_by_role_pos[(seg.slot_role, pos)] = seg
        role_seen[seg.slot_role] = pos + 1

    role_walk: dict[str, int] = {}
    for _slot_idx, slot in enumerate(skeleton):
        pos = role_walk.get(slot.role, 0)
        role_walk[slot.role] = pos + 1
        existing = seg_by_role_pos.get((slot.role, pos))
        if existing and not existing.is_fill:
            # Real binding from mapping — advance the cursor (using the
            # *same* output_span expression as mapping / renderer) and
            # remember its src range as the "nearest" for reuse.
            timeline_cursor = max(
                timeline_cursor,
                existing.timeline_start + _segment_output_span(existing),
            )
            last_real_src = existing.src_timerange
            continue
        if cur_gap is None:
            # No gap for this empty slot — should not normally happen since
            # detect_gaps emitted one Gap per uncovered slot. Defensive:
            # advance and keep walking.
            timeline_cursor += float(slot.duration.get("nominal", 1.0))
            continue
        # cur_gap belongs to this slot. Fill it.
        strategy = cur_gap.fill_strategy
        outcome: FillOutcome
        if strategy == "aigc_broll":
            # D10: only call the provider when the project opted in. Without
            # opt-in the "AI生成画面" slot quietly degrades to reuse — no event
            # spam, no cost, no degraded flag (it's the expected default).
            if allow_aigc_broll:
                seg, reasoning, degraded_msg = await _fill_aigc_broll(
                    slot,
                    timeline_cursor,
                    last_real_src,
                    ledger=ledger,
                    segments=segments,
                    template=template,
                    project_id=project_id,
                    task_id=task_id,
                    parent_event_id=parent_event_id,
                )
                outcome = FillOutcome(
                    gap_idx=cur_gap_idx if cur_gap_idx is not None else -1,
                    strategy="aigc_broll",
                    segment=seg,
                    reasoning=reasoning,
                    degraded_msg=degraded_msg,
                )
            else:
                seg = _reuse_segment_for(slot, timeline_cursor, last_real_src)
                outcome = FillOutcome(
                    gap_idx=cur_gap_idx if cur_gap_idx is not None else -1,
                    strategy="reuse",
                    segment=seg,
                    reasoning=(
                        "模板标「AI生成画面」但项目未勾选「允许 AI 补画面」，"
                        "降级到 reuse 策略（裁取相邻片段重复填入）。"
                    ),
                )
        elif strategy == "text_fill":
            text, reasoning = await _fill_text(
                cur_gap,
                slot,
                ledger=ledger,
                segments=segments,
                template=template,
                task_id=task_id,
                parent_event_id=parent_event_id,
            )
            seg = _wrap_segment_for(slot, timeline_cursor, last_real_src)
            cap_style = template.get_slot_caption(slot)
            cap = None
            if cap_style is not None:
                nominal = float(slot.duration.get("nominal", 1.5))
                cap = Caption(
                    text=text,
                    start=round(timeline_cursor, 3),
                    end=round(timeline_cursor + nominal, 3),
                    style=cap_style.model_copy(deep=True),
                )
            outcome = FillOutcome(
                gap_idx=cur_gap_idx if cur_gap_idx is not None else -1,
                strategy=strategy,
                text=text,
                segment=seg,
                caption=cap,
                reasoning=reasoning,
            )
        elif strategy == "wrap_fill":
            seg = _wrap_segment_for(slot, timeline_cursor, last_real_src)
            outcome = FillOutcome(
                gap_idx=cur_gap_idx if cur_gap_idx is not None else -1,
                strategy=strategy,
                segment=seg,
                reasoning="包装补全：复用相邻用户素材帧 + 套用模板贴纸 / 缩放层。",
            )
        else:  # reuse / default
            seg = _reuse_segment_for(slot, timeline_cursor, last_real_src)
            outcome = FillOutcome(
                gap_idx=cur_gap_idx if cur_gap_idx is not None else -1,
                strategy="reuse",
                segment=seg,
                reasoning="素材复用：裁取相邻片段的最后 0.5-1.0s，slow-motion 重复填入。",
            )
        outcomes.append(outcome)

        # Note: ``Gap.fill_result`` is written by the pipeline layer using
        # ``outcome.text`` / ``outcome.reasoning``. Keeping fill.py
        # side-effect-free on the gaps list makes it easier to test in
        # isolation and matches the rest of apply/'s "return values, don't
        # mutate inputs" discipline.

        # Advance timeline by the produced segment's *output* span.
        seg = outcome.segment
        if seg is not None:
            timeline_cursor += _segment_output_span(seg)

        # Use ``outcome.strategy`` (not the gap's requested ``strategy``) so the
        # event reflects what actually happened — e.g. an aigc_broll gap that
        # degraded to reuse because the project didn't opt in shows 2.fill.reuse.
        eff = outcome.strategy
        ev = VisionEvent(
            task_id=task_id,
            source="text_llm" if eff == "text_fill" else "system",
            stage=f"{STAGE}.{eff}",
            semantic_label=(
                f"缺口 #{cur_gap_idx} 补全 · {eff}"
                + (f" · '{outcome.text}'" if outcome.text else "")
                + (" · [degraded→reuse]" if outcome.degraded_msg else "")
            ),
            reasoning=outcome.reasoning or "（补全完成）",
            confidence=0.7 if eff == "text_fill" else 0.85,
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.gaps", op="append"),
            ir_value=cur_gap.model_dump(mode="json"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
        cur_gap_idx, cur_gap = next(gap_iter, (None, None))

    return outcomes, events


__all__ = ["STAGE", "FillOutcome", "fill_gaps"]
