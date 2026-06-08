"""1A-V7 · Geometric mask detection (VLM, two-stage classify when present)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from app.config import get_settings
from app.extract.frame_sampler import FrameSample
from app.extract.scenes import Scene
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, LLMClient, get_llm_client
from app.llm.prompts import load_prompt

STAGE = "1A.masks"


class _MaskParams(BaseModel):
    has_mask: bool = False
    kind: str | None = None
    params_norm_0_999: dict | None = None
    confidence: float = 0.0
    reasoning: str = ""

    def __workbench_label__(self) -> str:
        return "蒙版：有" if self.has_mask else "蒙版：无"


async def detect_masks(
    scenes: Sequence[Scene],
    frames: Sequence[FrameSample],
    *,
    task_id: str,
    parent_event_id: str | None = None,
    client: LLMClient | None = None,
) -> tuple[dict[int, _MaskParams], list[VisionEvent]]:
    """Per-scene VLM call. Falls through to no-mask when nothing found.

    The second-stage refinement is implicit in the prompt schema: if
    ``has_mask=true``, ``params_norm_0_999`` carries circle/rectangle/
    line_split parameters in the same response, so a single call covers
    both detection and parameter extraction.
    """
    settings = get_settings()
    cl = client or get_llm_client(stage=STAGE)
    out: dict[int, _MaskParams] = {}
    events: list[VisionEvent] = []
    for sc in scenes:
        mid_ts = (sc.start_sec + sc.end_sec) / 2
        frame = min(frames, key=lambda f: abs(f.ts - mid_ts)) if frames else None
        if frame is None:
            continue
        refs = [FrameRef(ts=frame.ts, url=frame.rel_path, scene_idx=frame.scene_idx)]
        messages = [
            {"role": "system", "content": load_prompt("1a_masks")},
            {
                "role": "user",
                "content": (
                    f"Scene {sc.idx} 的中间帧（@ {frame.ts:.2f}s）。请按 schema 判定有无几何蒙版。"
                ),
            },
        ]
        result, evs = await cl.chat_vision(
            messages,
            model=settings.model_vlm,
            stage=STAGE,
            task_id=task_id,
            frames=refs,
            ir_target_template=IRTarget(
                ir_type="TemplateIR", path=f"skeleton[{sc.idx}].style.visual"
            ),
            schema=_MaskParams,
            parent_event_id=parent_event_id,
        )
        out[sc.idx] = result
        events.extend(evs)
    return out, events
