"""1A-V4 + 1A-V5 · Zoom direction (VLM) + zoom keyframe curve (CV).

The two stages live in one module because they share one Scene-level
plan: the VLM judgement is the parent event, the CV refinement is the
child. Order of calls:

1. ``judge_zoom_direction(ctx, ...)`` — one VLM call per Scene over its
   first/mid/last frames → ``推进 / 拉远 / 稳定 / 抖动``. Each per-scene
   judgement writes ``Phase1AReport.zoom_directions[<scene_idx>]``.
2. ``estimate_zoom_curve(ctx, scene, ...)`` — only for non-stable Scenes,
   sample 5 points and run Lucas-Kanade optical flow on
   ``goodFeaturesToTrack`` keypoints → list of ``ZoomKeyframe`` written
   to ``Phase1AReport.zoom_curves[<scene_idx>]``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.extract.scenes import Scene
from app.ir.template import ZoomKeyframe
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef
from app.llm.prompts import load_prompt
from app.logging import get_logger

STAGE_DIRECTION = "1A.zoom_direction"
STAGE_CURVE = "1A.zoom_curve"
log = get_logger(__name__)


class _ZoomDirection(BaseModel):
    direction: str = "稳定"
    confidence: float = 0.0
    reasoning: str = ""

    def __workbench_label__(self) -> str:
        return f"缩放方向：{self.direction}"


async def judge_zoom_direction(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[dict[int, _ZoomDirection], list[VisionEvent]]:
    """One VLM call per scene, looking at its first/mid/last frames."""
    settings = get_settings()
    cl = ctx.client(STAGE_DIRECTION)
    scenes = await ctx.scenes()
    frames = await ctx.frames()
    out: dict[int, _ZoomDirection] = {}
    events: list[VisionEvent] = []
    for sc in scenes:
        sc_frames = _scene_anchor_frames(frames, sc)
        if not sc_frames:
            continue
        refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in sc_frames]
        messages = [
            {"role": "system", "content": load_prompt("1a_zoom_direction")},
            {
                "role": "user",
                "content": (
                    f"Scene {sc.idx}（{sc.start_sec:.2f}s–{sc.end_sec:.2f}s）的首/中/末三帧已附上。"
                ),
            },
        ]
        result, evs = await cl.chat_vision(
            messages,
            model=settings.model_vlm,
            stage=STAGE_DIRECTION,
            task_id=ctx.task_id,
            frames=refs,
            ir_target_template=IRTarget(
                ir_type="Phase1AReport", path=f"zoom_directions.{sc.idx}"
            ),
            schema=_ZoomDirection,
            parent_event_id=parent_event_id,
        )
        # Ensure the IR write is the direction string, not the whole schema dump.
        if evs:
            evs[0].ir_value = result.direction
        out[sc.idx] = result
        events.extend(evs)
    return out, events


async def estimate_zoom_curve(
    ctx: Phase1AContext,
    scene: Scene,
    *,
    parent_event_id: str | None = None,
    sample_count: int = 5,
) -> tuple[list[ZoomKeyframe], list[VisionEvent]]:
    """Lucas-Kanade optical flow over 5 sampled frames to estimate scale curve.

    Falls back to identity (scale=1.0) when OpenCV is missing.
    """
    bus = get_event_bus()
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning("motion.curve_dep_missing", error=str(e))
        ev = VisionEvent(
            task_id=ctx.task_id,
            source="cv",
            stage=STAGE_CURVE,
            semantic_label=f"[fallback] scene {scene.idx} 无缩放曲线",
            reasoning=f"OpenCV 不可用：{e}。沿用 scale=1.0。",
            confidence=0.3,
            parent_event_id=parent_event_id,
            duration_ms=0,
            severity="warning",
        )
        await bus.publish(ctx.task_id, ev)
        return [], [ev]

    cap = cv2.VideoCapture(str(ctx.normalized_path))
    if not cap.isOpened():
        return [], []
    try:
        duration = max(0.1, scene.end_sec - scene.start_sec)
        ts_list = [
            scene.start_sec + i * (duration / (sample_count - 1)) for i in range(sample_count)
        ]
        keyframes: list[ZoomKeyframe] = []
        prev_gray = None
        prev_pts = None
        first_distance: float | None = None
        for i, ts in enumerate(ts_list):
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is None:
                prev_gray = gray
                prev_pts = cv2.goodFeaturesToTrack(  # type: ignore[attr-defined]
                    gray, maxCorners=200, qualityLevel=0.01, minDistance=8
                )
                keyframes.append(ZoomKeyframe(relative_time=0.0, scale=1.0))
                continue
            if prev_pts is None or len(prev_pts) < 4:
                prev_gray = gray
                prev_pts = cv2.goodFeaturesToTrack(  # type: ignore[attr-defined]
                    gray, maxCorners=200, qualityLevel=0.01, minDistance=8
                )
                keyframes.append(ZoomKeyframe(relative_time=i / (sample_count - 1), scale=1.0))
                continue
            new_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, prev_pts, None)  # type: ignore[attr-defined]
            ok_idx = (status.flatten() == 1) if status is not None else None
            if ok_idx is None or ok_idx.sum() < 4:
                keyframes.append(ZoomKeyframe(relative_time=i / (sample_count - 1), scale=1.0))
            else:
                p0 = prev_pts[ok_idx].reshape(-1, 2)
                p1 = new_pts[ok_idx].reshape(-1, 2)
                # Distance from each pair to its centroid; ratio of mean
                # distances ≈ scale factor (camera zoom).
                c0 = p0.mean(axis=0)
                c1 = p1.mean(axis=0)
                d0 = np.linalg.norm(p0 - c0, axis=1).mean() or 1e-6  # type: ignore[attr-defined]
                d1 = np.linalg.norm(p1 - c1, axis=1).mean() or 1e-6  # type: ignore[attr-defined]
                if first_distance is None:
                    first_distance = float(d0)
                ratio = float(d1) / first_distance if first_distance else 1.0
                ratio = max(0.5, min(2.5, ratio))
                keyframes.append(
                    ZoomKeyframe(
                        relative_time=round(i / (sample_count - 1), 3),
                        scale=round(ratio, 3),
                    )
                )
            prev_gray = gray
            prev_pts = cv2.goodFeaturesToTrack(  # type: ignore[attr-defined]
                gray, maxCorners=200, qualityLevel=0.01, minDistance=8
            )
    finally:
        cap.release()

    ev = VisionEvent(
        task_id=ctx.task_id,
        source="cv",
        stage=STAGE_CURVE,
        media_ts_range=(float(scene.start_sec), float(scene.end_sec)),
        semantic_label=f"缩放曲线 · scene {scene.idx} · {len(keyframes)} 关键帧",
        reasoning="goodFeaturesToTrack + Lucas-Kanade 光流估算 scale 比率。",
        confidence=0.85,
        ir_target=IRTarget(
            ir_type="Phase1AReport",
            path=f"zoom_curves.{scene.idx}",
        ),
        ir_value=[k.model_dump(mode="json") for k in keyframes],
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
    await bus.publish(ctx.task_id, ev)
    return keyframes, [ev]


def _scene_anchor_frames(frames: Sequence[FrameSample], scene: Scene) -> list[FrameSample]:
    """Pick first/mid/last frames inside ``scene`` from the sample set."""
    inside = [f for f in frames if scene.start_sec <= f.ts < scene.end_sec]
    if len(inside) < 2:
        return inside
    return [inside[0], inside[len(inside) // 2], inside[-1]]
