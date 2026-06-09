"""1B · Template tag synthesis (VLM综合判).

Given an assembled TemplateIR + a few anchor frames, ask the VLM to
classify the template across PLAN.md's four tag axes:
- position (中间 / 顶部 / 底部 …)
- function (逻辑讲述 / 强调推销 / 教学讲解 / 情绪表达 …)
- scene (纯口播 / 口播+B-roll / 口播+图文 …)
- notes (free-form 30 字概要)

The call emits a single VisionEvent so the workbench right pane lights
up the ``tags`` field on TemplateIR as it fills in.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config import get_settings
from app.extract.frame_sampler import FrameSample
from app.ir.template import Tags, TemplateIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, get_llm_client

STAGE = "1B.tagging"


class _TagsResult(BaseModel):
    position: str = "中间"
    function: str = "逻辑讲述"
    scene: str = "纯口播"
    notes: str = ""

    def __workbench_label__(self) -> str:
        return f"标签：{self.function}/{self.scene}/{self.position}"


_SYSTEM_PROMPT = """你是视频剪辑模板的标签助手。给你一个模板的骨架摘要 + 3 张代表帧，请输出 JSON：
{
  "position": "中间|顶部|底部|多区域",
  "function": "逻辑讲述|强调推销|教学讲解|情绪表达|快节奏剪辑",
  "scene": "纯口播|口播+B-roll|口播+图文|口播+特效|纯展示",
  "notes": "<≤30 字中文描述这个模板的剪辑特点>"
}

只看模板的剪辑风格，不要重复原文。
"""


def _summarize_ir(ir: TemplateIR) -> str:
    """Compact text summary fed to the VLM as the user prompt."""
    slots_brief = []
    for i, slot in enumerate(ir.skeleton):
        cap = "有字幕" if slot.style.caption else "无字幕"
        zoom_n = len(slot.style.visual.zoom_keyframes)
        stickers_n = len(slot.style.stickers)
        slots_brief.append(
            f"  - slot {i} · {slot.role} · {slot.material_req} · "
            f"时长 {slot.duration.get('nominal', 0):.1f}s · {cap} · "
            f"zoom 关键帧 {zoom_n} · 贴纸 {stickers_n}"
        )
    audio_brief = "无 BGM"
    if ir.skeleton and ir.skeleton[0].style.audio.has_bgm:
        a = ir.skeleton[0].style.audio
        audio_brief = f"BGM {a.mood_tag or '?'} · BPM {a.bpm or 0:.0f}"
    return (
        f"模板「{ir.name}」骨架：{len(ir.skeleton)} 段\n"
        + "\n".join(slots_brief)
        + f"\n音频：{audio_brief}"
    )


async def suggest_tags(
    ir: TemplateIR,
    sample_frames: list[FrameSample],
    *,
    task_id: str,
    parent_event_id: str | None = None,
) -> tuple[Tags, list[VisionEvent]]:
    """One VLM call → Tags + the call's VisionEvent.

    Falls back (deterministic stub) when no credentials are configured;
    the warning event still surfaces in the workbench.
    """
    settings = get_settings()
    cl = get_llm_client(stage=STAGE)

    summary = _summarize_ir(ir)
    anchors = _pick_three(sample_frames)
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in anchors]

    user_prompt = "模板摘要：\n" + summary + "\n\n请按 schema 输出标签 JSON。"

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
        ir_target_template=IRTarget(ir_type="TemplateIR", path="tags"),
        schema=_TagsResult,
        parent_event_id=parent_event_id,
    )
    tags = Tags(
        position=result.position,
        function=result.function,
        scene=result.scene,
        notes=result.notes,
    )
    # Reshape the IR write to the canonical Tags structure so the workbench
    # tree shows the exact field names defined in template.py.
    if events:
        events[0].ir_value = tags.model_dump(mode="json")
    return tags, events


def _pick_three(frames: list[FrameSample]) -> list[FrameSample]:
    if not frames:
        return []
    if len(frames) <= 3:
        return frames
    n = len(frames)
    return [frames[0], frames[n // 2], frames[-1]]


__all__ = ["STAGE", "suggest_tags"]
