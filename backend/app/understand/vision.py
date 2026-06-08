"""Caption function classification — Phase 1A "phase2" downstream of captions.

This is a `*_classify`-named function so the
``scripts/check_parent_event_id.py`` CI script enforces the
``parent_event_id=`` keyword on the inner ``chat_vision`` call.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.config import get_settings
from app.extract.captions import CaptionEvent
from app.extract.frame_sampler import FrameSample
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, LLMClient, get_llm_client
from app.llm.prompts import load_prompt

STAGE = "1A.caption_function"


class _CaptionFunctionResult(BaseModel):
    function: str = "regular"
    confidence: float = 0.0
    reasoning: str = ""

    def __workbench_label__(self) -> str:
        return f"字幕功能：{self.function}"


async def classify_caption_function(
    caption: CaptionEvent,
    frame: FrameSample | None,
    *,
    task_id: str,
    parent_event_id: str | None = None,
    client: LLMClient | None = None,
) -> tuple[_CaptionFunctionResult, list[VisionEvent]]:
    """Run the function-classifier VLM call for a single CaptionEvent.

    The caption's existing style + placeholder + bbox are serialized into
    the user prompt as JSON; the model returns a single function label.
    """
    settings = get_settings()
    cl = client or get_llm_client(stage=STAGE)
    payload = {
        "style": caption.style.model_dump(mode="json"),
        "placeholder_text": caption.placeholder_text,
        "length_constraint": caption.length_constraint,
        "bbox_norm_0_999": list(caption.bbox_norm_0_999),
        "ts_window": [caption.start, caption.end],
    }
    user_prompt = (
        "请按 schema 给出 caption 功能分类。Caption 的样式、位置与占位信息如下：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    refs: list[FrameRef] = []
    if frame is not None:
        refs.append(FrameRef(ts=frame.ts, url=frame.rel_path, scene_idx=frame.scene_idx))
    messages = [
        {"role": "system", "content": load_prompt("1a_caption_function")},
        {"role": "user", "content": user_prompt},
    ]
    return await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=task_id,
        frames=refs or None,
        ir_target_template=IRTarget(ir_type="TemplateIR", path="skeleton[0].caption_function"),
        schema=_CaptionFunctionResult,
        parent_event_id=parent_event_id,
    )
