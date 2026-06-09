"""1B · Sanity check — VLM全局复查 the assembled TemplateIR.

A single VLM call answers: "given these representative frames + the IR
summary, does the template look internally consistent?" The output gets
written to ``TemplateIR.sanity_check``; the workbench shows the verdict
under that field as a yes/no with reasoning.

The check is intentionally lightweight (1 VLM call, not per-field
re-validation) — PLAN.md tags it as "整体复查" (verification 2 in the
validation list).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import get_settings
from app.extract.frame_sampler import FrameSample
from app.ir.template import TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, get_llm_client

STAGE = "1B.sanity_check"


class _SanityResult(BaseModel):
    ok: bool = True
    issues: list[str] = []
    placeholder_text_reasonable: bool = True
    reasoning: str = ""

    def __workbench_label__(self) -> str:
        return "sanity ✓" if self.ok else f"sanity ✗ ({len(self.issues)} issues)"


_SYSTEM_PROMPT = """你是视频剪辑模板的质量审计员。给你一个模板的 JSON 摘要 + 3 张样例帧，请按 schema 输出：

{
  "ok": true|false,
  "issues": ["问题1", "问题2", ...],
  "placeholder_text_reasonable": true|false,
  "reasoning": "<≤200 字中文总评>"
}

要复查：
1. 骨架顺序（开头→主体→结尾）是否合理；
2. 每个 slot 的 material_req 与 caption/sticker 是否自洽；
3. 字幕的 placeholder_text 描述是否符合样例帧里实际看到的字幕样式（不必抄字幕文字）；
4. zoom 关键帧的 scale 取值是否在合理范围（0.5~2.5）。
"""


async def sanity_check(
    ir: TemplateIR,
    sample_frames: list[FrameSample],
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[_SanityResult, list[VisionEvent]]:
    """One VLM call → verdict + event."""
    settings = get_settings()
    cl = get_llm_client(stage=STAGE)
    anchors = _pick_three(sample_frames)
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in anchors]

    summary = ir.model_dump_json(indent=None)[:2000]
    user_prompt = (
        "请审计以下模板（截断到 2000 字符）：\n" + summary + "\n\n按 schema 输出 JSON。"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    result, events = await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=task_id,
        frames=frame_refs or None,
        ir_target_template=IRTarget(ir_type="TemplateIR", path="sanity_check"),
        schema=_SanityResult,
        parent_event_id=parent_event_id,
    )
    return result, events


def _pick_three(frames: list[FrameSample]) -> list[FrameSample]:
    if not frames:
        return []
    if len(frames) <= 3:
        return frames
    n = len(frames)
    return [frames[0], frames[n // 2], frames[-1]]


__all__ = ["STAGE", "sanity_check"]
