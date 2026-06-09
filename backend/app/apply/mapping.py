"""2.map · short-material → template skeleton (PLAN 1599).

Strategy for 10-20s 一镜到底 口播:
- Walk through ASR Units in time order; each Unit goes into the current
  template slot until the slot's nominal duration is filled (with
  ±slot.duration.{min,max} band).
- When the slot fills, emit a PlacedSegment with ``src_timerange``
  = the user-material range covered, ``timeline_start`` = the slot's
  cumulative offset on the template's timeline, and ``speed`` =
  (template_slot_nominal / unit_span) clamped to ±20% (PLAN 1586).
- If the user material is shorter than the template skeleton:
  - All units bind to existing slots, scaled up to ≤1.2× speed.
  - Trailing slots without any unit coverage are flagged as Gaps
    (gaps.py handles those).
- If the user material is longer than the template skeleton:
  - Trailing units are either dropped (when fully past the last slot) or
    scaled down to ≥0.8× speed to fit. PLAN 1599: "时长超出时裁切尾部
    或顺延到下一槽".
  - A single warning event flags the user (no Gap because every slot
    DID get user content, just maybe overflowing).

Material-req matching is loose for MVP: if a slot's material_req is
"人物口播" we bind ASR units; otherwise (B-roll/包装) we leave it as a
Gap so fill.py can decide. PLAN 1600: "MVP 通常 Gap 数 ≤ 1（用户口播
覆盖人物口播槽，B-roll/包装槽可能 Gap）".
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger
from app.ir.project import PlacedSegment
from app.ir.template import Slot, StyleRule, TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

STAGE = "2.map"
log = get_logger(__name__)

# Speed clamp from PLAN 1586 — variable speed must not exceed ±20%.
_SPEED_MIN = 0.8
_SPEED_MAX = 1.2


@dataclass
class _SlotBinding:
    """Working state for a slot being filled by ASR units."""

    slot_idx: int
    slot: Slot
    unit_ids: list[int]
    src_start: float | None
    src_end: float | None


def _is_voice_slot(slot: Slot) -> bool:
    """Whether this slot expects ASR-driven user-material binding."""
    return slot.material_req in ("人物口播", "待定")


def _slot_nominal(slot: Slot) -> float:
    return float(slot.duration.get("nominal", 1.0))


def _slot_min(slot: Slot) -> float:
    return float(slot.duration.get("min", _slot_nominal(slot) * 0.7))


def _slot_max(slot: Slot) -> float:
    return float(slot.duration.get("max", _slot_nominal(slot) * 1.5))


def _clamp_speed(raw: float) -> float:
    """Bound speed to ±20% so apply never makes voice unnaturally fast/slow."""
    if raw < _SPEED_MIN:
        return _SPEED_MIN
    if raw > _SPEED_MAX:
        return _SPEED_MAX
    return raw


async def map_short_to_template(
    ledger: TranscriptLedger,
    template: TemplateIR,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[list[PlacedSegment], list[VisionEvent]]:
    """Bind ASR units to template voice slots in time order.

    Returns the placed segments and the events emitted. Pure mapping —
    style copying happens in style.py, gap filling in fill.py. Empty
    inputs return ([], []) without raising; the apply pipeline degrades
    on top of that.
    """
    started = time.perf_counter()
    bus = get_event_bus()
    segments: list[PlacedSegment] = []
    events: list[VisionEvent] = []

    if not ledger.units or not template.skeleton:
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.empty",
            semantic_label="映射跳过 · 无 Unit 或无骨架",
            reasoning=(
                f"ASR 给出 {len(ledger.units)} 个 Unit；模板骨架 "
                f"{len(template.skeleton)} 段。Mapping 无所作为。"
            ),
            confidence=0.0,
            severity="warning",
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.segments"),
            parent_event_id=parent_event_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        await bus.publish(task_id, ev)
        return [], [ev]

    user_total = ledger.units[-1].end - ledger.units[0].start
    template_total = sum(_slot_nominal(s) for s in template.skeleton)
    voice_slots = [s for s in template.skeleton if _is_voice_slot(s)]

    voice_total_nominal = sum(_slot_nominal(s) for s in voice_slots) or template_total
    global_scale = (
        voice_total_nominal / user_total if user_total > 0 else 1.0
    )

    # Build per-slot bindings sweeping through Units in time order. Each
    # voice slot accumulates units until its scaled target duration is
    # consumed (target = nominal / global_scale so the slot's *output*
    # plays at slot.nominal seconds while sourcing the right user-material
    # range).
    bindings: list[_SlotBinding] = [
        _SlotBinding(slot_idx=i, slot=s, unit_ids=[], src_start=None, src_end=None)
        for i, s in enumerate(template.skeleton)
    ]
    voice_binding_iter = iter(b for b in bindings if _is_voice_slot(b.slot))
    current_binding = next(voice_binding_iter, None)

    overflow_warning_emitted = False
    for unit in ledger.units:
        if current_binding is None:
            # All voice slots exhausted but units remain. PLAN 1599 says
            # "裁切尾部或顺延到下一槽" — we drop trailing units (the user
            # over-recorded) and emit one warning, not N (would spam).
            if not overflow_warning_emitted:
                ev = VisionEvent(
                    task_id=task_id,
                    source="system",
                    stage=f"{STAGE}.overflow",
                    semantic_label="[warning] 用户素材超出模板骨架",
                    reasoning=(
                        f"模板可绑定 voice slot 共 {len(voice_slots)} 个，"
                        "已铺满；后续 Unit 被裁切。建议用户使用更长模板或剪短素材。"
                    ),
                    confidence=0.5,
                    severity="warning",
                    ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.segments"),
                    parent_event_id=parent_event_id,
                )
                await bus.publish(task_id, ev)
                events.append(ev)
                overflow_warning_emitted = True
            continue

        unit_span = max(0.04, unit.end - unit.start)
        # Project the slot's nominal onto user-material space so we know how
        # much of the user clip should be consumed for this slot.
        slot_target_src = _slot_nominal(current_binding.slot) / max(0.04, global_scale)
        accrued_src = (current_binding.src_end or unit.start) - (
            current_binding.src_start or unit.start
        )

        if current_binding.src_start is None:
            current_binding.src_start = unit.start
        current_binding.unit_ids.append(unit.id)
        current_binding.src_end = unit.end

        if accrued_src + unit_span >= slot_target_src * 0.95:
            # Slot consumed enough source span — advance to the next voice slot.
            current_binding = next(voice_binding_iter, None)

    # Now flatten bindings into PlacedSegments in template order. Non-voice
    # slots with no binding become Gaps later; we still need a placeholder
    # segment so the timeline lines up.
    timeline_cursor = 0.0
    for binding in bindings:
        slot = binding.slot
        if binding.unit_ids and binding.src_start is not None and binding.src_end is not None:
            src_range = (binding.src_start, binding.src_end)
            src_span = max(0.04, binding.src_end - binding.src_start)
            target_nominal = _slot_nominal(slot)
            # speed = src duration / output duration; >1 = fast, <1 = slow
            raw_speed = src_span / max(0.04, target_nominal)
            speed = _clamp_speed(raw_speed)
            # Output span after speed clamp; this is what actually lands on
            # the timeline (may differ from slot.nominal if the raw speed
            # was clipped).
            output_span = src_span / speed
            # Re-band to slot.min/max if the clamped output overshoots.
            output_span = max(_slot_min(slot), min(_slot_max(slot), output_span))
            seg = PlacedSegment(
                slot_role=slot.role,
                source_unit_ids=binding.unit_ids,
                src_timerange=(round(src_range[0], 3), round(src_range[1], 3)),
                timeline_start=round(timeline_cursor, 3),
                speed=round(speed, 3),
                applied_style=StyleRule(),  # style.py fills this
                is_fill=False,
            )
            segments.append(seg)
            ev = VisionEvent(
                task_id=task_id,
                source="system",
                stage=STAGE,
                semantic_label=(
                    f"映射 slot#{binding.slot_idx} · {slot.role} · "
                    f"{len(binding.unit_ids)} 个 Unit · speed {speed:.2f}×"
                ),
                reasoning=(
                    f"绑定 Unit ids {binding.unit_ids}；"
                    f"src {src_range[0]:.2f}-{src_range[1]:.2f}s ({src_span:.2f}s) → "
                    f"timeline {timeline_cursor:.2f}-{timeline_cursor + output_span:.2f}s。"
                    f"raw_speed={raw_speed:.2f} 钳制到 ±20% 后={speed:.2f}。"
                ),
                confidence=0.9,
                ir_target=IRTarget(
                    ir_type="ProjectIR", path="sections.0.segments", op="append"
                ),
                ir_value=seg.model_dump(mode="json"),
                parent_event_id=parent_event_id,
            )
            await bus.publish(task_id, ev)
            events.append(ev)
            timeline_cursor += output_span
        else:
            # Slot expected user voice but got nothing (skeleton longer
            # than user material) OR it's a non-voice slot (B-roll/包装).
            # Either way, leave a zero-span placeholder so gaps.py can
            # spot it and emit a Gap. We DON'T add it to segments — gaps.py
            # checks "which skeleton slots got no PlacedSegment".
            ev = VisionEvent(
                task_id=task_id,
                source="system",
                stage=f"{STAGE}.gap_candidate",
                semantic_label=(
                    f"slot#{binding.slot_idx} · {slot.role} · 暂无映射"
                    f"（material_req={slot.material_req}）"
                ),
                reasoning=(
                    "用户素材已铺满或该槽位非 voice 类型；交由 gaps.py 处理。"
                ),
                confidence=0.3,
                ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.gaps", op="append"),
                parent_event_id=parent_event_id,
            )
            await bus.publish(task_id, ev)
            events.append(ev)
            # Advance the timeline cursor by the slot's nominal so later
            # filled gap segments line up correctly.
            timeline_cursor += _slot_nominal(slot)

    return segments, events


__all__ = ["STAGE", "map_short_to_template"]
