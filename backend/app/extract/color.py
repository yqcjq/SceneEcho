"""1A-V8 · Color / LUT semantic tagging (VLM + OpenCV histogram refine).

VLM gives subjective tags + ``dominant_lut_id`` from the user-provided
library; OpenCV computes HSV mean + histogram as a numerical refinement
event. Refinement is a "phase2" event keyed by parent_event_id.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.frame_sampler import FrameSample
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, LLMClient, get_llm_client
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "1A.color_lut"
log = get_logger(__name__)


class ColorStyleResult(BaseModel):
    tags: list[str] = Field(default_factory=list)
    dominant_lut_id: str | None = None
    confidence: float = 0.0
    reasoning: str = ""
    histogram: dict[str, float] | None = None  # filled by OpenCV refine

    def __workbench_label__(self) -> str:
        return f"调色：{'/'.join(self.tags) or 'unknown'}"


async def classify_color_lut(
    normalized_path: Path,
    frames: Sequence[FrameSample],
    *,
    task_id: str,
    parent_event_id: str | None = None,
    client: LLMClient | None = None,
    luts_index_rel: str = "system/luts/luts_index.json",
) -> tuple[ColorStyleResult, list[VisionEvent]]:
    """One VLM call over 3 anchor frames + one OpenCV refinement event."""
    if not frames:
        return ColorStyleResult(), []
    settings = get_settings()
    cl = client or get_llm_client(stage=STAGE)

    anchors = _pick_three(list(frames))
    refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in anchors]

    luts_summary = _read_luts_index(settings.resolve(luts_index_rel))
    luts_label = luts_summary or "（用户尚未配置 LUT 库；请给 dominant_lut_id=none）"
    user_prompt = f"请按 schema 给出主观调色标签 + dominant_lut_id。可选 LUT 库：{luts_label}"
    messages = [
        {"role": "system", "content": load_prompt("1a_color_lut")},
        {"role": "user", "content": user_prompt},
    ]
    result, events = await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=task_id,
        frames=refs,
        ir_target_template=IRTarget(ir_type="TemplateIR", path="global_style.color"),
        schema=ColorStyleResult,
        parent_event_id=parent_event_id,
    )
    refine_ev = await _refine_with_histogram(
        normalized_path,
        anchors,
        result,
        task_id=task_id,
        parent_event_id=events[0].event_id if events else parent_event_id,
    )
    if refine_ev is not None:
        events.append(refine_ev)
    return result, events


async def _refine_with_histogram(
    normalized_path: Path,
    anchors: list[FrameSample],
    result: ColorStyleResult,
    *,
    task_id: str,
    parent_event_id: str | None,
) -> VisionEvent | None:
    bus = get_event_bus()
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        return None

    cap = cv2.VideoCapture(str(normalized_path))
    if not cap.isOpened():
        return None
    try:
        h_means: list[float] = []
        s_means: list[float] = []
        v_means: list[float] = []
        for f in anchors:
            cap.set(cv2.CAP_PROP_POS_MSEC, f.ts * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            h_means.append(float(hsv[..., 0].mean()))
            s_means.append(float(hsv[..., 1].mean()))
            v_means.append(float(hsv[..., 2].mean()))
        if not h_means:
            return None
        hist = {
            "hue_mean": round(sum(h_means) / len(h_means), 2),
            "sat_mean": round(sum(s_means) / len(s_means), 2),
            "val_mean": round(sum(v_means) / len(v_means), 2),
        }
    finally:
        cap.release()

    result.histogram = hist
    ev = VisionEvent(
        task_id=task_id,
        source="cv",
        stage=STAGE,
        semantic_label=f"调色直方图 · 色相均值 {hist['hue_mean']:.0f}",
        reasoning=(
            f"OpenCV HSV 均值 hue={hist['hue_mean']:.1f}, sat={hist['sat_mean']:.1f}, "
            f"val={hist['val_mean']:.1f}。微调 VLM 主观标签："
            f"{'/'.join(result.tags) or 'unknown'}。"
        ),
        confidence=0.9,
        ir_target=IRTarget(ir_type="TemplateIR", path="global_style.color", field="histogram"),
        ir_value=hist,
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
    await bus.publish(task_id, ev)
    return ev


def _pick_three(frames: list[FrameSample]) -> list[FrameSample]:
    if len(frames) <= 3:
        return frames
    return [frames[0], frames[len(frames) // 2], frames[-1]]


def _read_luts_index(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ", ".join(f"{e.get('id', '?')}({e.get('category', '?')})" for e in data[:10])
    except Exception as e:  # noqa: BLE001
        log.warning("color.luts_index_parse_failed", error=str(e))
        return ""
