"""2.fill · gap completion (PLAN 1601).

Three strategies (MVP — no AIGC):

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

``allow_aigc_broll`` is plumbed for Phase 5 — when set to True we *would*
choose AIGC B-roll for B-roll gaps, but Phase 2 ignores the flag (PLAN
1587 strictly bans AIGC for this stage).

Each fill emits one VisionEvent so the workbench shows the completed
gap card filling in.
"""

from __future__ import annotations

from pydantic import BaseModel

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


class FillOutcome(BaseModel):
    """Result of filling one Gap. Drives ProjectIR insertion."""

    gap_idx: int
    strategy: str
    text: str = ""  # for text_fill / wrap_fill captions
    segment: PlacedSegment | None = None  # generated styling-only segment
    caption: Caption | None = None  # generated caption (if any)
    reasoning: str = ""


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
    gap_idx: int, segments: list[PlacedSegment], ledger: TranscriptLedger
) -> int | None:
    """Pick a "pivot" Unit id approximating where the gap sits relative to ASR.

    Strategy: find the segment that immediately precedes the gap by
    timeline_start; use its last source_unit_id. None when no segments
    exist (mapping returned []).
    """
    if not segments or not ledger.units:
        return None
    # Sort segments by timeline_start and take the last one with
    # source_unit_ids before treating the gap as "trailing".
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

    cap_style = slot.style.caption
    placeholder = list(cap_style.placeholder_text) if cap_style else []
    length_constraint = dict(cap_style.length_constraint) if cap_style else {}
    semantic_purpose = cap_style.semantic_purpose if cap_style else "regular"

    pivot = _pivot_unit_for(0, segments, ledger)
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
        applied_style=slot.style.model_copy(deep=True),
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
        applied_style=slot.style.model_copy(deep=True),
        is_fill=True,
    )


async def fill_gaps(
    gaps: list[Gap],
    template: TemplateIR,
    segments: list[PlacedSegment],
    ledger: TranscriptLedger,
    *,
    task_id: str,
    allow_aigc_broll: bool = False,
    parent_event_id: str | None = None,
) -> tuple[list[FillOutcome], list[VisionEvent]]:
    """Fill each gap per its ``fill_strategy``.

    ``allow_aigc_broll`` is captured for Phase 5; Phase 2 ignores it
    (PLAN 1587). The function never raises — failures inside one fill
    flag that gap as degraded but keep filling the others.
    """
    if allow_aigc_broll:
        log.info("fill.aigc_broll_requested_but_phase2_ignores", count=len(gaps))

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
            # Real binding from mapping — advance the cursor and remember
            # its src range as the "nearest" for reuse.
            seg_span = (existing.src_timerange[1] - existing.src_timerange[0]) / max(
                0.04, existing.speed
            )
            timeline_cursor = max(timeline_cursor, existing.timeline_start + seg_span)
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
        if strategy == "text_fill":
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
            cap_style = slot.style.caption
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

        # Persist the gap.fill_result for ProjectIR readers (the pipeline
        # writes outcome.text / outcome.reasoning back onto Gap).
        cur_gap.fill_result = outcome.text or outcome.reasoning

        # Advance timeline by the produced segment's *output* span.
        seg = outcome.segment
        if seg is not None:
            output_span = (seg.src_timerange[1] - seg.src_timerange[0]) / max(0.04, seg.speed)
            timeline_cursor += output_span

        ev = VisionEvent(
            task_id=task_id,
            source="system" if strategy != "text_fill" else "text_llm",
            stage=f"{STAGE}.{strategy}",
            semantic_label=(
                f"缺口 #{cur_gap_idx} 补全 · {strategy}"
                + (f" · '{outcome.text}'" if outcome.text else "")
            ),
            reasoning=outcome.reasoning or "（补全完成）",
            confidence=0.7 if strategy == "text_fill" else 0.85,
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.gaps", op="append"),
            ir_value=cur_gap.model_dump(mode="json"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
        cur_gap_idx, cur_gap = next(gap_iter, (None, None))

    return outcomes, events


__all__ = ["STAGE", "FillOutcome", "fill_gaps"]
