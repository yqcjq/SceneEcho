"""1A · B-roll / 画面构成 detection (VLM main path).

decisions/010 决策 6（ISS-023）落地：每个 scene 取中间帧给 VLM 判定画面
构成 4 类（人物主导 / 全屏 B-roll / 画中画 / 侧栏）+ 可选 ROI bbox。
Phase 5 ``generate_broll`` 直接消费 ``Phase1AReport.b_roll_segments``
判断哪段该启用 AI 补画面；本期 1A 不触发任何 AIGC 调用，仅落识别字段。

scene 采样策略：取每个 scene 内 1 fps 抽样集合的中间帧（与 zoom_direction
相同的"中点帧"语义）。若 scene 时长 < 1s 没有抽样帧，则跳过该 scene。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.extract.scenes import Scene
from app.ir.phase1a_report import BRollSegment
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "1A.b_roll"
log = get_logger(__name__)


class _BRollRaw(BaseModel):
    """Strict schema for one VLM-returned BRollSegment row."""

    kind: Literal[
        "人物主导", "全屏 B-roll", "画中画", "侧栏"
    ] = "人物主导"
    bbox_norm_0_999: list[int] | None = None
    confidence: float = 0.0
    reasoning: str = ""


async def detect_b_roll(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[list[BRollSegment], list[VisionEvent]]:
    """Per-scene VLM call: classify frame composition + optional ROI.

    Returns ``([BRollSegment per scene], [emitted events])``. Each scene
    emits exactly one entity event with ``ir_target.path="b_roll_segments"``
    and ``op="append"`` so the workbench right pane lights up sequentially.
    Scenes that fall back to the default (人物主导) still emit so the user
    can see the system actually looked at every scene.
    """
    bus = get_event_bus()
    settings = get_settings()
    cl = ctx.client(STAGE)
    scenes = await ctx.scenes()
    frames = await ctx.frames()

    out: list[BRollSegment] = []
    events: list[VisionEvent] = []
    for sc in scenes:
        anchor = _scene_middle_frame(frames, sc)
        if anchor is None:
            continue
        ref = FrameRef(ts=anchor.ts, url=anchor.rel_path, scene_idx=anchor.scene_idx)
        messages = [
            {"role": "system", "content": load_prompt("1a_b_roll")},
            {
                "role": "user",
                "content": (
                    f"Scene {sc.idx}（{sc.start_sec:.2f}s–{sc.end_sec:.2f}s）的中间帧已附上。"
                    "请判断画面构成类型。"
                ),
            },
        ]
        result, evs = await cl.chat_vision(
            messages,
            model=settings.model_vlm,
            stage=STAGE,
            task_id=ctx.task_id,
            frames=[ref],
            ir_target_template=None,  # call-level event; entity event below carries the IR write
            schema=_BRollRaw,
            parent_event_id=parent_event_id,
        )
        events.extend(evs)
        call_ev_id = evs[0].event_id if evs else parent_event_id

        bbox = _bbox_from_raw(result)
        segment = BRollSegment(
            scene_idx=sc.idx,
            kind=result.kind,
            start=float(sc.start_sec),
            end=float(sc.end_sec),
            bbox_norm_0_999=bbox,
            confidence=result.confidence,
            reasoning=result.reasoning[:200],
        )
        entity_ev = VisionEvent(
            task_id=ctx.task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            frame_ts=anchor.ts,
            frame_url=f"/data/{anchor.rel_path.lstrip('/')}",
            bbox_norm=tuple(float(v) for v in bbox) if bbox else None,
            media_ts=float(anchor.ts),
            media_ts_range=(float(sc.start_sec), float(sc.end_sec)),
            semantic_label=f"画面构成：{result.kind}",
            reasoning=result.reasoning[:200],
            confidence=result.confidence,
            ir_target=IRTarget(
                ir_type="Phase1AReport", path="b_roll_segments", op="append"
            ),
            ir_value=segment.model_dump(mode="json"),
            parent_event_id=call_ev_id,
            duration_ms=0,
        )
        await bus.publish(ctx.task_id, entity_ev)
        events.append(entity_ev)
        out.append(segment)
    return out, events


def _scene_middle_frame(
    frames: list[FrameSample], scene: Scene
) -> FrameSample | None:
    """Pick the frame nearest to the scene's temporal midpoint.

    Falls through to None when no sampled frame falls inside the scene
    (extremely short scene or sampler gap).
    """
    inside = [f for f in frames if scene.start_sec <= f.ts < scene.end_sec]
    if not inside:
        return None
    midpoint = (scene.start_sec + scene.end_sec) / 2.0
    return min(inside, key=lambda f: abs(f.ts - midpoint))


def _bbox_from_raw(raw: _BRollRaw) -> tuple[int, int, int, int] | None:
    """Validate VLM bbox; reject malformed / out-of-range values.

    Returns None when:
    - bbox is None or absent (kind=人物主导 / 全屏 B-roll legitimately omits it);
    - the list is shorter than 4;
    - any coord is outside [0, 999];
    - w / h is implausibly small (< 50, ~5% frame).
    """
    if not raw.bbox_norm_0_999:
        return None
    if len(raw.bbox_norm_0_999) < 4:
        return None
    try:
        x = int(raw.bbox_norm_0_999[0])
        y = int(raw.bbox_norm_0_999[1])
        w = int(raw.bbox_norm_0_999[2])
        h = int(raw.bbox_norm_0_999[3])
    except (TypeError, ValueError):
        return None
    if w < 50 or h < 50:
        return None
    if any(v < 0 or v > 999 for v in (x, y, w, h)):
        return None
    return (x, y, w, h)


__all__ = ["BRollSegment", "STAGE", "detect_b_roll"]
