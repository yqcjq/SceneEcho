"""1A-V3 · Sticker detection (VLM grid sampling + CV bbox refine).

Two-stage pipeline (the canonical "parent_event_id chain" the workbench
gantt view consumes):
1. VLM call with up to 6 frames laid out as a grid → list of stickers
   with rough position + semantic_category.
2. CV refine pass on each detected sticker — Canny edge + frame-diff
   inside the VLM-given bbox ±10% → tightened to ±5px.

Each detection appends to ``Phase1AReport.stickers`` so the workbench's
right pane lights up the new row; the refine event re-writes the same
entry in place once CV tightens the bbox.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.ir.phase1a_report import Phase1AStickerDetection
from app.ir.template import StickerEvent
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef
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
class _RefineRequest:
    """In-process holder for a sticker pending its CV refine call."""

    detection: Phase1AStickerDetection
    sticker_idx: int
    parent_event_id: str


async def detect_stickers(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[list[Phase1AStickerDetection], list[VisionEvent]]:
    frames = await ctx.frames()
    if not frames:
        return [], []
    settings = get_settings()
    cl = ctx.client(STAGE)
    bus = get_event_bus()

    limited = list(frames)[:6]
    frame_refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in limited]
    user_prompt = (
        f"请按 schema 识别贴纸。采样帧时间戳依次为 {[round(f.ts, 2) for f in limited]}（秒）。"
        "frames_appeared 用 0-indexed 整数对应上述时间戳数组的下标。"
    )
    messages = [
        {"role": "system", "content": load_prompt("1a_stickers")},
        {"role": "user", "content": user_prompt},
    ]
    result, events = await cl.chat_vision(
        messages,
        model=settings.model_vlm,
        stage=STAGE,
        task_id=ctx.task_id,
        frames=frame_refs,
        ir_target_template=None,  # call-level event has no IR write
        schema=StickersRawResult,
        parent_event_id=parent_event_id,
    )
    call_ev_id = events[0].event_id if events else parent_event_id

    detections: list[Phase1AStickerDetection] = []
    pending_refine: list[_RefineRequest] = []
    for raw in result.stickers:
        bbox = _bbox_norm(raw)
        anchor_idx = next((i for i in raw.frames_appeared if 0 <= i < len(limited)), None)
        if anchor_idx is None:
            continue
        anchor = limited[anchor_idx]
        ts_appeared = [limited[i].ts for i in raw.frames_appeared if 0 <= i < len(limited)]
        sticker = StickerEvent(
            description=raw.description[:60] or "未命名贴纸",
            position=(round(bbox[0] / 1000, 4), round(bbox[1] / 1000, 4)),
            size=(round(bbox[2] / 1000, 4), round(bbox[3] / 1000, 4)),
            start=min(ts_appeared),
            end=max(ts_appeared) + 0.5,
            semantic_category=raw.semantic_category,
        )
        detection = Phase1AStickerDetection(
            sticker=sticker,
            bbox_norm_0_999=bbox,
            frames_appeared=ts_appeared,
            confidence=raw.confidence,
            reasoning=raw.reasoning[:200],
        )
        sticker_idx = len(detections)  # 0-based index in Phase1AReport.stickers
        # Entity-level event: append to Phase1AReport.stickers + carry the
        # anchor frame URL so the workbench left pane can show the frame
        # image with the sticker bbox overlay.
        entity = VisionEvent(
            task_id=ctx.task_id,
            source="vlm",
            model_used=settings.model_vlm,
            stage=STAGE,
            frame_ts=anchor.ts,
            frame_url=f"/data/{anchor.rel_path.lstrip('/')}",
            bbox_norm=tuple(float(v) for v in bbox),
            media_ts=float(anchor.ts),
            semantic_label=f"贴纸：{raw.semantic_category} · {raw.description[:20]}",
            reasoning=raw.reasoning[:200],
            confidence=raw.confidence,
            ir_target=IRTarget(ir_type="Phase1AReport", path="stickers", op="append"),
            ir_value=detection.model_dump(mode="json"),
            parent_event_id=call_ev_id,
            duration_ms=0,
        )
        await bus.publish(ctx.task_id, entity)
        events.append(entity)
        detections.append(detection)
        pending_refine.append(
            _RefineRequest(detection=detection, sticker_idx=sticker_idx, parent_event_id=entity.event_id)
        )

    # Refine pass (CV) — only when OpenCV is present; otherwise skip silently.
    for req in pending_refine:
        refine_ev = await refine_sticker_bbox(
            ctx,
            req.detection,
            sticker_idx=req.sticker_idx,
            parent_event_id=req.parent_event_id,
        )
        if refine_ev is not None:
            events.append(refine_ev)
    return detections, events


async def refine_sticker_bbox(
    ctx: Phase1AContext,
    detection: Phase1AStickerDetection,
    *,
    sticker_idx: int,
    parent_event_id: str,
) -> VisionEvent | None:
    """Tighten the bbox to the dominant sticker contour inside ±10% of VLM bbox.

    Algorithm (二轮优化): Canny edges → ``findContours(RETR_EXTERNAL)`` →
    score each contour by ``area / (1 + distance_to_roi_center)`` →
    ``boundingRect`` of the winner. Replaces the previous min/max bbox
    over *all* edge points, which was pathologically wide whenever the
    ±10% ROI included any other visual content (faces, captions, texture).

    The function name is a "phase2"-style refine — the
    ``check_parent_event_id`` CI script keys on this naming convention.
    """
    bus = get_event_bus()
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning("stickers.refine_dep_missing", error=str(e))
        return None

    cap = cv2.VideoCapture(str(ctx.normalized_path))
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
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 160)
        # Light dilate so contour ends close — sticker outlines are often
        # broken by anti-aliasing.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        new_bbox = _pick_best_contour_bbox(contours, roi.shape[:2], W, H, x0, y0, cv2)
        if new_bbox is None:
            return None
    finally:
        cap.release()

    # Apply to detection (pydantic — model_copy + reassign for clarity).
    detection.bbox_norm_0_999 = new_bbox
    detection.sticker = detection.sticker.model_copy(
        update={
            "position": (round(new_bbox[0] / 1000, 4), round(new_bbox[1] / 1000, 4)),
            "size": (round(new_bbox[2] / 1000, 4), round(new_bbox[3] / 1000, 4)),
        }
    )

    # Resolve the anchor frame's rel_path from the cached frames so the
    # refine event also carries a frame_url + bbox the workbench can render.
    cached_frames = await ctx.frames()
    anchor_ts = detection.frames_appeared[0]
    anchor_frame = (
        min(cached_frames, key=lambda f: abs(f.ts - anchor_ts)) if cached_frames else None
    )
    frame_url = (
        f"/data/{anchor_frame.rel_path.lstrip('/')}" if anchor_frame is not None else None
    )

    ev = VisionEvent(
        task_id=ctx.task_id,
        source="cv",
        stage=STAGE,
        frame_ts=anchor_ts,
        frame_url=frame_url,
        bbox_norm=tuple(float(v) for v in new_bbox),
        media_ts=float(anchor_ts),
        semantic_label="CV 精化贴纸 bbox 至最大连通轮廓",
        reasoning=(
            "Canny 边缘 → findContours(RETR_EXTERNAL) → "
            "按 area / (1 + 距 ROI 中心距离) 评分挑出最大主轮廓的 boundingRect。"
        ),
        confidence=0.94,
        ir_target=IRTarget(
            ir_type="Phase1AReport",
            path=f"stickers[{sticker_idx}]",
        ),
        ir_value=detection.model_dump(mode="json"),
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
    await bus.publish(ctx.task_id, ev)
    return ev


def _pick_best_contour_bbox(
    contours,
    roi_shape: tuple[int, int],
    W: int,
    H: int,
    x0: int,
    y0: int,
    cv2,
) -> tuple[int, int, int, int] | None:
    """Score each contour by area weighted against distance to ROI center.

    Sticker assumption: VLM's bbox is approximately right, so the true
    sticker contour will (a) carry most of the ink in the ROI and (b) sit
    near the ROI center. Scoring ``area / (1 + dist_to_center)`` punishes
    far-flung noise blobs and tiny edge fragments equally. Tiny contours
    (<10 px²) are pre-filtered to avoid divide-by-zero on degenerate moments.
    """
    if not contours:
        return None
    roi_h, roi_w = roi_shape
    cx_roi = roi_w / 2.0
    cy_roi = roi_h / 2.0
    best_score = 0.0
    best_rect: tuple[int, int, int, int] | None = None
    for c in contours:
        area = float(cv2.contourArea(c))
        if area < 10:
            continue
        m = cv2.moments(c)
        if m["m00"] == 0:
            continue
        cx = m["m10"] / m["m00"]
        cy = m["m01"] / m["m00"]
        dist = ((cx - cx_roi) ** 2 + (cy - cy_roi) ** 2) ** 0.5
        score = area / (1.0 + dist)
        if score > best_score:
            bx, by, bw, bh = cv2.boundingRect(c)
            best_score = score
            best_rect = (bx, by, bw, bh)
    if best_rect is None:
        return None
    bx, by, bw, bh = best_rect
    return (
        int((bx + x0) / W * 1000),
        int((by + y0) / H * 1000),
        int(bw / W * 1000),
        int(bh / H * 1000),
    )


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


# Back-compat alias — older tests may still import StickerDetection.
StickerDetection = Phase1AStickerDetection

__all__ = [
    "Phase1AStickerDetection",
    "STAGE",
    "StickerDetection",
    "StickersRawResult",
    "detect_stickers",
    "refine_sticker_bbox",
]
