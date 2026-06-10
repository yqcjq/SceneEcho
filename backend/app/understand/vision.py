"""Caption function classification — Phase 1A "phase2" downstream of captions.

This is a ``*_classify``-named function so the
``scripts/check_parent_event_id.py`` CI script enforces the
``parent_event_id=`` keyword on the inner ``chat_vision`` call.

decisions/011 落地后输出升级为 ``Phase1ACaptionFunctionEvent``：除原 ``function`` 字段外
新增 ``anim_in_type / anim_emphasis / stagger_ms_estimate / role_in_template`` 字段，
承担 captions_anim 子能力删除后的动画语义识别。返回的事件 ``ir_target`` 指向
``Phase1AReport.caption_functions`` 而非 ``captions[idx].function``。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.config import get_settings
from app.extract.captions import CaptionEvent
from app.extract.frame_sampler import FrameSample
from app.ir.phase1a_report import Phase1ACaptionFunctionEvent
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, LLMClient, get_llm_client
from app.llm.prompts import load_prompt

STAGE = "1A.caption_function"


class _CaptionFunctionResult(BaseModel):
    function: str = "regular"
    anim_in_type: str = "unknown"
    anim_emphasis: str | None = None
    stagger_ms_estimate: int | None = None
    role_in_template: str | None = None
    confidence: float = 0.0
    reasoning: str = ""

    def __workbench_label__(self) -> str:
        return f"字幕功能：{self.function} · 动画：{self.anim_in_type}"


async def classify_caption_function(
    caption: CaptionEvent,
    frame: FrameSample | None,
    *,
    task_id: str,
    caption_idx: int,
    parent_event_id: str | None = None,
    client: LLMClient | None = None,
) -> tuple[Phase1ACaptionFunctionEvent, list[VisionEvent]]:
    """Run the function-classifier VLM call for a single CaptionEvent.

    ``caption_idx`` indexes into ``Phase1AReport.captions`` and is also
    threaded onto the returned ``Phase1ACaptionFunctionEvent`` so callers
    can join. The emitted ``VisionEvent`` writes to ``Phase1AReport
    .caption_functions`` (append op) — pipeline aggregator collects them
    into a list parallel to ``captions``.
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
        "请按 schema 给出 caption 功能 + 动画分类。Caption 的样式、位置与占位信息如下：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    refs: list[FrameRef] = []
    if frame is not None:
        refs.append(FrameRef(ts=frame.ts, url=frame.rel_path, scene_idx=frame.scene_idx))
    messages = [
        {"role": "system", "content": load_prompt("1a_caption_function")},
        {"role": "user", "content": user_prompt},
    ]
    result, events = await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=task_id,
        frames=refs or None,
        ir_target_template=IRTarget(
            ir_type="Phase1AReport",
            path="caption_functions",
            op="append",
        ),
        schema=_CaptionFunctionResult,
        parent_event_id=parent_event_id,
    )
    fn_event = Phase1ACaptionFunctionEvent(
        caption_idx=caption_idx,
        function=result.function or "regular",  # type: ignore[arg-type]
        anim_in_type=result.anim_in_type or "unknown",  # type: ignore[arg-type]
        anim_emphasis=result.anim_emphasis,
        stagger_ms_estimate=result.stagger_ms_estimate,
        role_in_template=result.role_in_template,
        confidence=result.confidence,
        reasoning=(result.reasoning or "")[:200],
    )
    # Re-shape the published event so workbench right-pane shows the
    # CaptionFunctionEvent (not the loose schema) + carry the caption's bbox
    # so the bbox overlay renders alongside the verdict.
    if events:
        events[0].ir_value = fn_event.model_dump(mode="json")
        events[0].bbox_norm = tuple(float(v) for v in caption.bbox_norm_0_999)
    return fn_event, events
