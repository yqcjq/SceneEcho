"""1A-V4 + 1A-V5 · Zoom direction (VLM) + zoom keyframe curve (CV).

The two stages live in one module because they share one Scene-level
plan: the VLM judgement is the parent event, the CV refinement is the
child. Order of calls:

1. ``judge_zoom_direction(ctx, ...)`` — one VLM call per Scene over its
   first/mid/last frames → 13 classes (4 zoom: 推进 / 拉远 / 稳定 / 抖动 +
   8 pan: 左移 / 右移 / 上移 / 下移 + 4 diagonal). Each per-scene judgement
   writes ``Phase1AReport.zoom_directions[<scene_idx>]``.
2. ``estimate_zoom_curve(ctx, scene, ...)`` — only for non-stable Scenes,
   sample 5 points and run Lucas-Kanade optical flow on
   ``goodFeaturesToTrack`` keypoints → list of ``ZoomKeyframe`` (含
   ``scale`` 缩放比率 + ``dx``/``dy`` 归一化平移位移) written to
   ``Phase1AReport.zoom_curves[<scene_idx>]``.

ISS-021 改造（decisions/010 决策 5）：
- direction 从 4 类扩到 13 类（加 8 平移方向）。
- ZoomKeyframe 加 ``dx`` / ``dy`` 字段表达镜头平移：cumulative centroid
  drift between scene-first frame and frame i, normalized to frame width
  / height. 渲染端 ZoomLayer.tsx 在 P5 阶段消费这两个字段做 translateX /
  translateY 联合变换，实现 "向左推进 = scale > 1 同时 dx > 0" 的 3-DoF
  镜头表达。
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


# decisions/010 决策 5：13 类方向。保留为 frozenset 让 prompt 与代码双向校验。
# Pure-pan 与 diagonal-pan 走 "non-stable" 分支驱动 estimate_zoom_curve。
ZOOM_DIRECTIONS_13 = frozenset(
    {
        "推进", "拉远", "稳定", "抖动",
        "左移", "右移", "上移", "下移",
        "左上移", "右上移", "左下移", "右下移",
    }
)


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
    """One VLM call per scene, looking at its first/mid/last frames.

    VLM 返回 13 类方向之一（见 ``ZOOM_DIRECTIONS_13``）；非该集合内的
    返回值降级为 ``稳定`` 以保证下游 ``estimate_zoom_curve`` 不会被误触。
    """
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
        if result.direction not in ZOOM_DIRECTIONS_13:
            log.warning(
                "motion.unknown_direction",
                scene=sc.idx,
                direction=result.direction,
            )
            result = result.model_copy(update={"direction": "稳定"})
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
    """Lucas-Kanade optical flow over 5 sampled frames to estimate scale + pan.

    每帧的 ZoomKeyframe 同时输出 (scale, dx, dy)：
    - scale = ratio of mean keypoint-to-centroid distance (camera zoom).
    - dx / dy = centroid drift relative to the scene's first frame, normalized
      to frame width / height (camera pan in [-1, 1] range, typically much
      smaller).

    跟踪策略：从 scene 首帧抽取 ``goodFeaturesToTrack`` keypoint set，所有
    后续帧均从首帧 LK 光流追踪到当前帧（不是连续帧追踪）——这样 dx / dy
    自然就是「相对首帧的累积位移」，无需手动累加。光流跟丢（< 4 个有效
    keypoint）时该帧降级为 (1.0, 0.0, 0.0)。

    Falls back to identity (scale=1.0, dx=0, dy=0) when OpenCV is missing.
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
            reasoning=f"OpenCV 不可用：{e}。沿用 scale=1.0 / dx=dy=0。",
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
        first_gray = None
        first_pts = None
        frame_W = 0
        frame_H = 0
        for i, ts in enumerate(ts_list):
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if first_gray is None:
                first_gray = gray
                frame_H, frame_W = gray.shape[:2]
                first_pts = cv2.goodFeaturesToTrack(  # type: ignore[attr-defined]
                    gray, maxCorners=200, qualityLevel=0.01, minDistance=8
                )
                keyframes.append(
                    ZoomKeyframe(relative_time=0.0, scale=1.0, dx=0.0, dy=0.0)
                )
                continue
            if first_pts is None or len(first_pts) < 4:
                keyframes.append(
                    ZoomKeyframe(
                        relative_time=round(i / (sample_count - 1), 3),
                        scale=1.0,
                        dx=0.0,
                        dy=0.0,
                    )
                )
                continue
            # Track the *first* frame's keypoints to the current frame so
            # dx / dy / scale are all relative to scene start (not the prev
            # frame). Sliding-window prev_gray would accumulate drift error.
            new_pts, status, _ = cv2.calcOpticalFlowPyrLK(  # type: ignore[attr-defined]
                first_gray, gray, first_pts, None
            )
            ok_idx = (status.flatten() == 1) if status is not None else None
            if ok_idx is None or ok_idx.sum() < 4:
                keyframes.append(
                    ZoomKeyframe(
                        relative_time=round(i / (sample_count - 1), 3),
                        scale=1.0,
                        dx=0.0,
                        dy=0.0,
                    )
                )
                continue
            # All four (c0 / c1 / d0 / d1) are computed from the same ok-idx
            # subset — so the scale / pan ratios stay self-consistent even
            # when LK loses keypoints (e.g. on zoom-in: edge keypoints fall
            # out of frame, only central ones remain). Using a "first-frame
            # full-keypoint" baseline against a subset c1 would mix two
            # different reference points and skew dx / dy on heavy drop-out.
            p0 = first_pts[ok_idx].reshape(-1, 2)
            p1 = new_pts[ok_idx].reshape(-1, 2)
            c0 = p0.mean(axis=0)
            c1 = p1.mean(axis=0)
            d0 = np.linalg.norm(p0 - c0, axis=1).mean() or 1e-6  # type: ignore[attr-defined]
            d1 = np.linalg.norm(p1 - c1, axis=1).mean() or 1e-6  # type: ignore[attr-defined]
            scale_ratio = max(0.5, min(2.5, float(d1) / float(d0)))
            dx_norm = (
                (float(c1[0]) - float(c0[0])) / frame_W if frame_W else 0.0
            )
            dy_norm = (
                (float(c1[1]) - float(c0[1])) / frame_H if frame_H else 0.0
            )
            # Clamp pan to [-0.5, 0.5] — half a frame is the maximum
            # plausible single-scene pan; anything beyond is optical-flow
            # noise from a scene cut the detector missed.
            dx_norm = max(-0.5, min(0.5, dx_norm))
            dy_norm = max(-0.5, min(0.5, dy_norm))
            keyframes.append(
                ZoomKeyframe(
                    relative_time=round(i / (sample_count - 1), 3),
                    scale=round(scale_ratio, 3),
                    dx=round(dx_norm, 4),
                    dy=round(dy_norm, 4),
                )
            )
    finally:
        cap.release()

    ev = VisionEvent(
        task_id=ctx.task_id,
        source="cv",
        stage=STAGE_CURVE,
        media_ts_range=(float(scene.start_sec), float(scene.end_sec)),
        semantic_label=f"缩放 + 平移曲线 · scene {scene.idx} · {len(keyframes)} 关键帧",
        reasoning=(
            "goodFeaturesToTrack + Lucas-Kanade 光流（首帧 keypoint 跟踪到各采样帧）"
            "估算每帧的 scale 比率与 (dx, dy) 归一化位移。"
        ),
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
