"""1A-V7 · Geometric mask detection (CV primary + VLM fallback).

二核反馈：单帧 VLM 在 mask 上不稳定，scene 中点恰好没蒙版就漏报；CV 算法
（HoughCircles / Canny 矩形 / HoughLinesP）在几何形状清晰时确定性强、
不需要截帧给 VLM。

策略：
1. CV 主路径：scene 内首/中/末三帧分别跑三种几何检测器，多数决判定有无 +
   类型 + 参数。
2. VLM 兜底：CV 全部判 has_mask=False（或置信度低）时，再调一次 VLM 看
   多帧合一组的网格图，避免 CV 漏检半透明 / 自然纹理边缘的情况。

每个 scene 的最终判定写入 ``Phase1AReport.masks[<scene_idx>]``，事件
``frame_url`` 指向最强证据帧（CV 检出的那一帧 / VLM 用的中间帧）方便工作台
左栏 bbox 可视化。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.extract.scenes import Scene
from app.ir.phase1a_report import Phase1AMaskParams
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE = "1A.masks"
log = get_logger(__name__)

# CV detector confidence thresholds — tuned to bias toward false-negative
# (let VLM fallback catch missed cases) rather than false-positive.
_CIRCLE_HOUGH_PARAM2 = 35
_RECTANGLE_MIN_AREA_FRAC = 0.10  # rectangle must cover ≥10% of frame
_LINE_MIN_LENGTH_FRAC = 0.60     # split line must span ≥60% of frame


@dataclass
class _CVCandidate:
    kind: str  # "circle" | "rectangle" | "line_split"
    params: dict
    bbox_norm: tuple[int, int, int, int] | None
    confidence: float
    frame: FrameSample


async def detect_masks(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[dict[int, Phase1AMaskParams], list[VisionEvent]]:
    """Per-scene: CV multi-frame vote → fallback VLM if all CV votes are no-mask.

    Returns ``{scene_idx: Phase1AMaskParams}`` and the emitted events. Each
    scene contributes at most one IR-write event (CV-decided or VLM-decided),
    plus optional debug events for the per-frame CV probes.
    """
    bus = get_event_bus()
    scenes = await ctx.scenes()
    frames = await ctx.frames()
    out: dict[int, Phase1AMaskParams] = {}
    events: list[VisionEvent] = []

    for sc in scenes:
        anchors = _scene_anchor_frames(frames, sc)
        if not anchors:
            continue
        cv_result, cv_evs = await _cv_vote(ctx, sc, anchors)
        events.extend(cv_evs)
        if cv_result is not None and cv_result.has_mask:
            out[sc.idx] = cv_result
            ir_ev = _make_ir_event(
                ctx.task_id,
                sc.idx,
                cv_result,
                source="cv",
                anchor=anchors[len(anchors) // 2],
                reasoning=(
                    f"CV 三帧多数决判定 {cv_result.kind} mask · "
                    f"confidence {cv_result.confidence:.2f}。"
                ),
                parent_event_id=parent_event_id,
            )
            await bus.publish(ctx.task_id, ir_ev)
            events.append(ir_ev)
            continue
        # CV says no-mask (or all probes inconclusive) — let VLM look at the
        # same three frames as a grid before we record a final no-mask.
        vlm_result, vlm_evs = await _vlm_fallback(ctx, sc, anchors, parent_event_id)
        events.extend(vlm_evs)
        if vlm_result is not None:
            out[sc.idx] = vlm_result
    return out, events


# ---------------------------------------------------------------------------
# CV path
# ---------------------------------------------------------------------------


async def _cv_vote(
    ctx: Phase1AContext, scene: Scene, anchors: list[FrameSample]
) -> tuple[Phase1AMaskParams | None, list[VisionEvent]]:
    """Run three detectors on each anchor frame; majority-vote the result.

    Returns (None, []) when OpenCV isn't installed. Each per-frame probe
    that finds something emits a ``severity="info"`` event with the
    candidate bbox + frame_url so the workbench shows what CV saw.
    """
    bus = get_event_bus()
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        return None, []

    candidates: list[_CVCandidate] = []
    events: list[VisionEvent] = []
    cap = cv2.VideoCapture(str(ctx.normalized_path))
    if not cap.isOpened():
        return None, []
    try:
        for anchor in anchors:
            cap.set(cv2.CAP_PROP_POS_MSEC, anchor.ts * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            H, W = gray.shape[:2]
            for cand in _detect_circle(gray, cv2, np, W, H):
                cand.frame = anchor
                candidates.append(cand)
            for cand in _detect_rectangle(gray, cv2, np, W, H):
                cand.frame = anchor
                candidates.append(cand)
            for cand in _detect_line_split(gray, cv2, np, W, H):
                cand.frame = anchor
                candidates.append(cand)
    finally:
        cap.release()

    # Emit one info event per CV candidate (not too noisy: at most 3 frames
    # × 3 detectors = 9 per scene, typically far fewer).
    for c in candidates:
        events.append(
            VisionEvent(
                task_id=ctx.task_id,
                source="cv",
                stage=STAGE,
                frame_ts=c.frame.ts,
                frame_url=f"/data/{c.frame.rel_path.lstrip('/')}",
                bbox_norm=tuple(float(v) for v in c.bbox_norm) if c.bbox_norm else None,
                media_ts=float(c.frame.ts),
                semantic_label=f"CV 候选：{c.kind} · confidence {c.confidence:.2f}",
                reasoning=(
                    f"scene {scene.idx} 第 {anchors.index(c.frame)} 帧 OpenCV "
                    f"{c.kind} 检测命中，参数：{c.params}。"
                ),
                confidence=c.confidence,
                duration_ms=0,
            )
        )
        await bus.publish(ctx.task_id, events[-1])

    decision = _majority_vote(candidates, len(anchors))
    return decision, events


def _detect_circle(gray, cv2, np, W: int, H: int) -> list[_CVCandidate]:
    """HoughCircles — round masks (avatar circles, vignettes)."""
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.0,
        minDist=min(W, H) // 2,
        param1=120,
        param2=_CIRCLE_HOUGH_PARAM2,
        minRadius=min(W, H) // 8,
        maxRadius=min(W, H) // 2,
    )
    if circles is None:
        return []
    out = []
    for cx, cy, r in circles[0]:
        if r < min(W, H) * 0.10:
            continue
        out.append(
            _CVCandidate(
                kind="circle",
                params={
                    "cx": int(cx / W * 1000),
                    "cy": int(cy / H * 1000),
                    "radius": int(r / min(W, H) * 1000),
                },
                bbox_norm=(
                    int((cx - r) / W * 1000),
                    int((cy - r) / H * 1000),
                    int((2 * r) / W * 1000),
                    int((2 * r) / H * 1000),
                ),
                confidence=0.85,
                frame=None,  # type: ignore[arg-type]
            )
        )
    return out


def _detect_rectangle(gray, cv2, np, W: int, H: int) -> list[_CVCandidate]:
    """Largest rectangular contour above a min-area threshold."""
    edges = cv2.Canny(gray, 80, 160)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    frame_area = W * H
    for c in contours:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) != 4:
            continue
        x, y, w, h = cv2.boundingRect(approx)
        area = w * h
        if area < frame_area * _RECTANGLE_MIN_AREA_FRAC:
            continue
        if area > frame_area * 0.95:
            # full-frame rectangle is the canvas border, not a mask
            continue
        # Aspect ratio check: skip extremely thin slivers (likely text bars).
        if min(w, h) < min(W, H) * 0.15:
            continue
        out.append(
            _CVCandidate(
                kind="rectangle",
                params={
                    "x": int(x / W * 1000),
                    "y": int(y / H * 1000),
                    "w": int(w / W * 1000),
                    "h": int(h / H * 1000),
                },
                bbox_norm=(
                    int(x / W * 1000),
                    int(y / H * 1000),
                    int(w / W * 1000),
                    int(h / H * 1000),
                ),
                confidence=0.80,
                frame=None,  # type: ignore[arg-type]
            )
        )
    return sorted(out, key=lambda c: -(c.params["w"] * c.params["h"]))[:1]


def _detect_line_split(gray, cv2, np, W: int, H: int) -> list[_CVCandidate]:
    """HoughLinesP — split-screen lines spanning most of the frame."""
    edges = cv2.Canny(gray, 80, 160)
    min_len = int(min(W, H) * _LINE_MIN_LENGTH_FRAC)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=3.14159 / 180,
        threshold=120,
        minLineLength=min_len,
        maxLineGap=20,
    )
    if lines is None:
        return []
    out = []
    for ln in lines[:5]:
        x1, y1, x2, y2 = ln[0]
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        # Only accept near-horizontal or near-vertical splits.
        if dx > 0 and dy / dx > 0.15 and dx / max(dy, 1) > 0.15:
            continue
        side = (
            "top"
            if dx > dy and (y1 + y2) / 2 < H / 2
            else "bottom"
            if dx > dy
            else "left"
            if (x1 + x2) / 2 < W / 2
            else "right"
        )
        out.append(
            _CVCandidate(
                kind="line_split",
                params={
                    "x1": int(x1 / W * 1000),
                    "y1": int(y1 / H * 1000),
                    "x2": int(x2 / W * 1000),
                    "y2": int(y2 / H * 1000),
                    "side_kept": side,
                },
                bbox_norm=None,
                confidence=0.70,
                frame=None,  # type: ignore[arg-type]
            )
        )
    return out[:1]


def _majority_vote(
    candidates: list[_CVCandidate], n_frames: int
) -> Phase1AMaskParams | None:
    """Need >= ceil(n_frames / 2) candidates of the same kind to confirm."""
    if not candidates:
        return None
    by_kind: dict[str, list[_CVCandidate]] = {}
    for c in candidates:
        by_kind.setdefault(c.kind, []).append(c)
    quorum = max(2, (n_frames + 1) // 2)
    for kind, group in by_kind.items():
        if len(group) >= quorum:
            best = max(group, key=lambda c: c.confidence)
            return Phase1AMaskParams(
                has_mask=True,
                kind=kind,  # type: ignore[arg-type]
                params_norm_0_999={kind: best.params},
                confidence=best.confidence,
            )
    return None


# ---------------------------------------------------------------------------
# VLM fallback
# ---------------------------------------------------------------------------


async def _vlm_fallback(
    ctx: Phase1AContext,
    scene: Scene,
    anchors: list[FrameSample],
    parent_event_id: str | None,
) -> tuple[Phase1AMaskParams | None, list[VisionEvent]]:
    """Last resort — VLM looks at first/mid/last frames as a 3-frame grid."""
    settings = get_settings()
    cl = ctx.client(STAGE)
    refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in anchors]
    messages = [
        {"role": "system", "content": load_prompt("1a_masks")},
        {
            "role": "user",
            "content": (
                f"Scene {scene.idx}（{scene.start_sec:.2f}s–{scene.end_sec:.2f}s）的"
                f"首/中/末三帧已附上。CV 三帧多数决判定无几何蒙版，请你复核。"
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
            ir_type="Phase1AReport", path=f"masks.{scene.idx}"
        ),
        schema=Phase1AMaskParams,
        parent_event_id=parent_event_id,
    )
    return result, evs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scene_anchor_frames(frames: list[FrameSample], scene: Scene) -> list[FrameSample]:
    """Pick first / mid / last frames inside the scene from the sample set."""
    inside = [f for f in frames if scene.start_sec <= f.ts < scene.end_sec]
    if len(inside) <= 3:
        return inside
    return [inside[0], inside[len(inside) // 2], inside[-1]]


def _make_ir_event(
    task_id: str,
    scene_idx: int,
    result: Phase1AMaskParams,
    *,
    source: str,
    anchor: FrameSample,
    reasoning: str,
    parent_event_id: str | None,
) -> VisionEvent:
    bbox: tuple[float, float, float, float] | None = None
    if result.params_norm_0_999 and result.kind:
        p = result.params_norm_0_999.get(result.kind)
        if isinstance(p, dict):
            if result.kind == "circle" and "cx" in p and "radius" in p:
                bbox = (
                    float(p["cx"] - p["radius"]),
                    float(p["cy"] - p["radius"]),
                    float(2 * p["radius"]),
                    float(2 * p["radius"]),
                )
            elif result.kind == "rectangle":
                bbox = (float(p["x"]), float(p["y"]), float(p["w"]), float(p["h"]))
    return VisionEvent(
        task_id=task_id,
        source=source,  # type: ignore[arg-type]
        stage=STAGE,
        frame_ts=anchor.ts,
        frame_url=f"/data/{anchor.rel_path.lstrip('/')}",
        bbox_norm=bbox,
        media_ts=float(anchor.ts),
        semantic_label=f"几何蒙版：{result.kind} (scene {scene_idx})",
        reasoning=reasoning,
        confidence=result.confidence,
        ir_target=IRTarget(ir_type="Phase1AReport", path=f"masks.{scene_idx}"),
        ir_value=result.model_dump(mode="json"),
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
