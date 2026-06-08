"""1A-V6 · Transition classification (VLM)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from app.config import get_settings
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef
from app.llm.prompts import load_prompt

STAGE = "1A.transitions"


class _TransitionResult(BaseModel):
    transition: str = "硬切"
    confidence: float = 0.0
    reasoning: str = ""

    def __workbench_label__(self) -> str:
        return f"转场：{self.transition}"


async def classify_transitions(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[dict[int, _TransitionResult], list[VisionEvent]]:
    """One VLM call per adjacent scene boundary.

    Each per-boundary judgement writes
    ``Phase1AReport.transitions[<prev_scene_idx>]``.
    """
    settings = get_settings()
    cl = ctx.client(STAGE)
    scenes = await ctx.scenes()
    frames = await ctx.frames()
    out: dict[int, _TransitionResult] = {}
    events: list[VisionEvent] = []
    for i in range(len(scenes) - 1):
        prev_sc = scenes[i]
        next_sc = scenes[i + 1]
        boundary_ts = next_sc.start_sec
        prev_frame = _frame_near(frames, boundary_ts - 0.1)
        mid_frame = _frame_near(frames, boundary_ts)
        next_frame = _frame_near(frames, boundary_ts + 0.1)
        anchor = [f for f in (prev_frame, mid_frame, next_frame) if f is not None]
        if not anchor:
            continue
        refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in anchor]
        messages = [
            {"role": "system", "content": load_prompt("1a_transitions")},
            {
                "role": "user",
                "content": (
                    f"相邻 scene {prev_sc.idx} → {next_sc.idx} 的边界 @ {boundary_ts:.2f}s。"
                    "首张为前镜头末帧，第二张为过渡中间帧，最后一张为下镜头首帧。"
                ),
            },
        ]
        result, evs = await cl.chat_vision(
            messages,
            model=settings.model_vlm,
            stage=STAGE,
            task_id=ctx.task_id,
            frames=refs,
            ir_target_template=IRTarget(
                ir_type="Phase1AReport", path=f"transitions.{prev_sc.idx}"
            ),
            schema=_TransitionResult,
            parent_event_id=parent_event_id,
        )
        if evs:
            evs[0].ir_value = result.transition
        out[prev_sc.idx] = result
        events.extend(evs)
    return out, events


def _frame_near(frames: Sequence[FrameSample], ts: float) -> FrameSample | None:
    if not frames:
        return None
    return min(frames, key=lambda f: abs(f.ts - ts))
