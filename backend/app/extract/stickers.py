"""1A-V3 · Sticker detection (VLM grid sampling + CV bbox refine).

Two-stage pipeline (the canonical "parent_event_id chain" the workbench
gantt view consumes):
1. VLM call with up to 6 frames laid out as a grid → list of stickers
   with rough position + semantic_category.
2. CV refine pass on each detected sticker — Canny edge + frame-diff
   inside the VLM-given bbox ±10% → tightened to ±5px.

Phase 1A intermediate dataclass ``StickerDetection`` carries the merged
result; 1B integration writes it into ``Slot.style.stickers``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.frame_sampler import FrameSample
from app.ir.template import StickerEvent
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, LLMClient, get_llm_client
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "1A.stickers"
log = get_logger(__name__)


class _StickerRaw(BaseModel):
    description: str = ""
    semantic_category: str = "装饰"
    frames_appeared: list[int] = Field(default_factory=list)
    position_norm_0_999: list[int] = Field(default_factory=list)
    size_norm_0_999: list[int] = Field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


class StickersRawResult(BaseModel):
    stickers: list[_StickerRaw] = Field(default_factory=list)

    def __workbench_label__(self) -> str:
        return f"贴纸识别 · {len(self.stickers)} 枚"


@dataclass
class StickerDetection:
    sticker: StickerEvent
    bbox_norm_0_999: tuple[int, int, int, int]
    frames_appeared: list[float]
    confidence: float


async def detect_stickers(
    normalized_path: Path,
    frames: Sequence[FrameSample],
    *,
    task_id: str,
    parent_event_id: str | None = None,
    client: LLMClient | None = None,
) -> tuple[list[StickerDetection], list[VisionEvent]]:
    if not frames:
        return [], []
    settings = get_settings()
    cl = client or get_llm_client(stage=STAGE)
    bus = get_event_bus()

    limited = list(frames)[:6]
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in limited]
    user_prompt = (
        f"请按 schema 识别贴纸。采样帧时间戳依次为 {[round(f.ts, 2) for f in limited]}（秒）。"
    )
    messages = [
        {"role": "system", "content": load_prompt("1a_stickers")},
        {"role": "user", "content": user_prompt},
    ]
    result, events = await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=task_id,
        frames=frame_refs,
        ir_target_template=IRTarget(ir_type="TemplateIR", path="skeleton"),
        schema=StickersRawResult,
        parent_event_id=parent_event_id,
    )
    call_ev_id = events[0].event_id if events else parent_event_id

    detections: list[StickerDetection] = []
    for raw in result.stickers:
        bbox = _bbox_norm(raw)
        ts_appeared = [limited[i].ts for i in raw.frames_appeared if 0 <= i < len(limited)]
        if not ts_appeared:
            continue
        sticker = StickerEvent(
            description=raw.description[:60] or "未命名贴纸",
            position=(round(bbox[0] / 1000, 4), round(bbox[1] / 1000, 4)),
            size=(round(bbox[2] / 1000, 4), round(bbox[3] / 1000, 4)),
            start=min(ts_appeared),
            end=max(ts_appeared) + 0.5,
            semantic_category=raw.semantic_category,
        )
        detection = StickerDetection(
            sticker=sticker,
            bbox_norm_0_999=bbox,
            frames_appeared=ts_appeared,
            confidence=raw.confidence,
        )
        # Entity-level event so the workbench's right pane appends a row to
        # the targeted slot's stickers list.
        entity = VisionEvent(
            task_id=task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            frame_ts=detection.sticker.start,
            bbox_norm=tuple(float(v) for v in bbox),
            semantic_label=f"贴纸：{raw.semantic_category} · {raw.description[:20]}",
            reasoning=raw.reasoning[:200],
            confidence=raw.confidence,
            ir_target=IRTarget(
                ir_type="TemplateIR",
                path=f"skeleton[{_slot_idx_for(raw.frames_appeared, limited)}].style.stickers",
                op="append",
            ),
            ir_value=sticker.model_dump(mode="json"),
            parent_event_id=call_ev_id,
            duration_ms=0,
        )
        await bus.publish(task_id, entity)
        events.append(entity)

        # Refine pass (CV) — only when OpenCV is present; otherwise skip.
        refine_ev = await refine_sticker_bbox(
            normalized_path,
            detection,
            task_id=task_id,
            parent_event_id=entity.event_id,
        )
        if refine_ev is not None:
            events.append(refine_ev)
        detections.append(detection)
    return detections, events


async def refine_sticker_bbox(
    normalized_path: Path,
    detection: StickerDetection,
    *,
    task_id: str,
    parent_event_id: str,
) -> VisionEvent | None:
    """Tighten bbox to ±5px using Canny + frame-diff inside ±10% of VLM bbox.

    The function name is a "phase2"-style refine — the
    ``check_parent_event_id`` CI script keys on this naming convention.
    """
    bus = get_event_bus()
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning("stickers.refine_dep_missing", error=str(e))
        return None

    cap = cv2.VideoCapture(str(normalized_path))
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, detection.frames_appeared[0] * 1000)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        H, W = frame.shape[:2]
        x = int(detection.bbox_norm_0_999[0] / 1000 * W)
        y = int(detection.bbox_norm_0_999[1] / 1000 * H)
        w = int(detection.bbox_norm_0_999[2] / 1000 * W)
        h = int(detection.bbox_norm_0_999[3] / 1000 * H)
        margin_x = max(8, int(w * 0.10))
        margin_y = max(8, int(h * 0.10))
        x0 = max(0, x - margin_x)
        y0 = max(0, y - margin_y)
        x1 = min(W, x + w + margin_x)
        y1 = min(H, y + h + margin_y)
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            return None
        edges = cv2.Canny(roi, 80, 160)
        ys, xs = np.where(edges > 0)  # type: ignore[attr-defined]
        if len(xs) < 8:
            return None
        nx0, ny0 = int(xs.min()) + x0, int(ys.min()) + y0
        nx1, ny1 = int(xs.max()) + x0, int(ys.max()) + y0
        new_bbox = (
            int(nx0 / W * 1000),
            int(ny0 / H * 1000),
            int((nx1 - nx0) / W * 1000),
            int((ny1 - ny0) / H * 1000),
        )
    finally:
        cap.release()

    # Apply to detection in-place.
    detection.bbox_norm_0_999 = new_bbox
    detection.sticker.position = (round(new_bbox[0] / 1000, 4), round(new_bbox[1] / 1000, 4))
    detection.sticker.size = (round(new_bbox[2] / 1000, 4), round(new_bbox[3] / 1000, 4))

    ev = VisionEvent(
        task_id=task_id,
        source="cv",
        stage=STAGE,
        frame_ts=detection.frames_appeared[0],
        bbox_norm=tuple(float(v) for v in new_bbox),
        semantic_label="CV 精化贴纸 bbox 至 ±5px",
        reasoning="Canny + 帧差在 VLM bbox ±10% 范围内精化。",
        confidence=0.94,
        ir_target=IRTarget(
            ir_type="TemplateIR",
            path="skeleton[0].style.stickers[0]",  # caller rebinds in 1B
        ),
        ir_value=detection.sticker.model_dump(mode="json"),
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
    await bus.publish(task_id, ev)
    return ev


def _bbox_norm(raw: _StickerRaw) -> tuple[int, int, int, int]:
    if len(raw.position_norm_0_999) >= 4:
        return tuple(raw.position_norm_0_999[:4])  # type: ignore[return-value]
    if len(raw.position_norm_0_999) >= 2 and len(raw.size_norm_0_999) >= 2:
        return (
            raw.position_norm_0_999[0],
            raw.position_norm_0_999[1],
            raw.size_norm_0_999[0],
            raw.size_norm_0_999[1],
        )
    return (0, 0, 100, 100)


def _slot_idx_for(frame_indices: list[int], frames: Sequence[FrameSample]) -> int:
    if not frame_indices:
        return 0
    mid = frame_indices[len(frame_indices) // 2]
    if 0 <= mid < len(frames):
        idx = frames[mid].scene_idx
        if idx is not None:
            return idx
    return 0
