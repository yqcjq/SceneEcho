"""2.gaps · template slots without PlacedSegment coverage (PLAN 1600).

A Gap is a template Slot whose ``material_req`` was not satisfied by the
mapping pass. There are two flavours:

1. **Voice gap**: ``material_req="人物口播"``. User material was too short
   to cover this slot. fill.py's text-fill strategy (LLM-generated caption)
   is the typical resolution. Marked ``reason="无用户语音覆盖"``,
   ``fill_strategy="text_fill"``.
2. **B-roll gap**: ``material_req="B-roll/包装"`` or similar. The user
   doesn't have B-roll to begin with; the template's style hints (sticker
   placeholders, zoom keyframes, generated_image=None) flag this as
   "packaging only" → fill.py's wrap-fill emits a styling-only segment
   with placeholder visuals. Marked ``reason="模板期望 B-roll，用户未提供"``,
   ``fill_strategy="wrap_fill"``.

For Phase 2 MVP we don't synthesize AIGC B-roll (PLAN 1587 banned AIGC for
this stage); the wrap-fill segment relies on sticker placeholders + a
slowed/repeated frame from adjacent user material (handled by fill.py's
``reuse`` strategy when wrap_fill alone is insufficient).
"""

from __future__ import annotations

import time

from app.event_bus import get_event_bus
from app.ir.project import Gap, PlacedSegment
from app.ir.template import Slot, TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

STAGE = "2.gaps"
log = get_logger(__name__)


def _slot_has_segment(slot_idx: int, segments: list[PlacedSegment], template: TemplateIR) -> bool:
    """Whether ``segments`` contains a binding for the given slot index.

    Mapping doesn't carry slot_idx on PlacedSegment, but slot_role + the
    order-preserving emit makes a positional match sufficient: the i-th
    voice segment in ``segments`` (matching role) corresponds to the i-th
    voice slot in the skeleton. We index by role-aware position.
    """
    if slot_idx < 0 or slot_idx >= len(template.skeleton):
        return False
    target_role = template.skeleton[slot_idx].role
    # Count how many earlier slots in the skeleton share this role.
    earlier_same = sum(
        1 for i in range(slot_idx) if template.skeleton[i].role == target_role
    )
    # Walk segments and find the (earlier_same + 1)-th of target_role.
    seen = 0
    for seg in segments:
        if seg.slot_role == target_role and not seg.is_fill:
            if seen == earlier_same:
                return True
            seen += 1
    return False


def _strategy_for(slot: Slot) -> tuple[str, str]:
    """Return ``(reason, fill_strategy)`` per Gap policy in module docstring.

    Named ``_strategy_for`` (not ``_classify_gap``) so the CI
    ``check_parent_event_id`` guard — which matches the ``classify_`` prefix
    as "phase-2 AI sub-step" — doesn't flag this pure rule-based function.
    Same first-principles fix as ISS-010 #9 (``_classify_role`` →
    ``_role_for_position``): if no AI call happens, the name shouldn't
    suggest one.
    """
    if slot.material_req == "AI生成画面":
        # Phase 5 (ISS-028): the template marked this slot as wanting AI-
        # generated B-roll. fill.py routes ``aigc_broll`` through generate_broll
        # *only* when the project opted in (allow_aigc_broll); otherwise it
        # degrades to reuse. gaps.py stays a pure function of material_req — it
        # doesn't know the opt-in flag, so it always tags the intent here.
        return "模板期望 AI 补画面（B-roll）", "aigc_broll"
    if slot.material_req == "人物口播":
        return "无用户语音覆盖", "text_fill"
    if slot.material_req == "B-roll/包装":
        return "模板期望 B-roll，用户未提供", "wrap_fill"
    return "槽位未绑定且素材类型未定", "reuse"


async def detect_gaps(
    segments: list[PlacedSegment],
    template: TemplateIR,
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[list[Gap], list[VisionEvent]]:
    """Return one Gap per template slot lacking PlacedSegment coverage.

    Pure detection — does not mutate ``segments`` and doesn't pick fill
    text. fill.py is the only writer.
    """
    started = time.perf_counter()
    bus = get_event_bus()
    gaps: list[Gap] = []
    events: list[VisionEvent] = []
    for i, slot in enumerate(template.skeleton):
        if _slot_has_segment(i, segments, template):
            continue
        reason, strategy = _strategy_for(slot)
        gap = Gap(
            slot_role=slot.role,
            reason=reason,
            fill_strategy=strategy,
            fill_result="",
        )
        gaps.append(gap)
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=STAGE,
            semantic_label=f"缺口 #{len(gaps) - 1} · slot#{i} {slot.role} · {strategy}",
            reasoning=(
                f"slot#{i} (role={slot.role}, material_req={slot.material_req}) 无 "
                f"PlacedSegment 覆盖；reason={reason}；fill_strategy={strategy}。"
            ),
            confidence=0.85,
            ir_target=IRTarget(
                ir_type="ProjectIR", path="sections.0.gaps", op="append"
            ),
            ir_value=gap.model_dump(mode="json"),
            parent_event_id=parent_event_id,
        )
        await bus.publish(task_id, ev)
        events.append(ev)

    if not gaps:
        ev = VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.empty",
            semantic_label="无缺口 · 所有 slot 都已绑定 PlacedSegment",
            reasoning="mapping 已铺满；fill.py 跳过。",
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="sections.0.gaps"),
            parent_event_id=parent_event_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        await bus.publish(task_id, ev)
        events.append(ev)

    return gaps, events


__all__ = ["STAGE", "detect_gaps"]
