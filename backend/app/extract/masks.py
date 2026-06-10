"""1A-V7 · Geometric mask detection (CV circle + VLM main path).

二核 ISS-020 改造：移除 ``_detect_rectangle`` / ``_detect_line_split`` —
口播视频里几乎不出现真矩形 / 分屏蒙版，但字幕带 / 标题条 / 水印 / logo 在
Canny + Hough 检测器面前形态高度相似，三个原 CV 检测器加起来贡献的几乎
全是误报（9 个字幕首现位置全部被当作几何 mask 标到 MediaTimeline 上）。
保留 ``_detect_circle``：圆形蒙版（头像框 / vignette）形态足够独特，
HoughCircles 不会被字幕带触发。

策略变化：
1. CV 主路径只跑 ``_detect_circle`` 的多帧投票（圆形蒙版的判定能力 CV 强于 VLM）。
2. 圆形以外的几何蒙版（矩形画框、分屏、不规则）一律走 VLM 兜底——VLM 看
   多帧合一组的网格图，prompt 显式要求排除字幕 / 标题条 / 水印 / UI 元素。
3. CV 检不到圆且 VLM 判 has_mask=false → 该 scene 无几何蒙版。

decisions/010 已知代价 3：删 CV 矩形/分屏后真实矩形/分屏蒙版完全靠 VLM；
项目定位为口播视频，矩形 / 线分屏蒙版极少出现，VLM 单帧识别精度不构成
demo 阶段约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: F401  (kept for type hints in helpers)

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

# Circle detector confidence threshold — tuned to bias toward false-negative
# (let VLM fallback catch missed cases) rather than false-positive.
_CIRCLE_HOUGH_PARAM2 = 35


@dataclass
class _CVCandidate:
    kind: str  # "circle" only after ISS-020 cleanup
    params: dict
    bbox_norm: tuple[int, int, int, int] | None
    confidence: float
    frame: FrameSample


async def detect_masks(
    ctx: Phase1AContext,
    *,
    parent_event_id: str | None = None,
) -> tuple[dict[int, Phase1AMaskParams], list[VisionEvent]]:
    """Per-scene: CV circle vote → VLM fallback for non-circle masks.

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
        # CV says no-circle (or all probes inconclusive) — fall back to VLM
        # for non-circle geometries (rectangle / line_split / nothing).
        vlm_result, vlm_evs = await _vlm_fallback(ctx, sc, anchors, parent_event_id)
        events.extend(vlm_evs)
        if vlm_result is not None:
            out[sc.idx] = vlm_result
    return out, events


# ---------------------------------------------------------------------------
# CV path — circle only after ISS-020
# ---------------------------------------------------------------------------


async def _cv_vote(
    ctx: Phase1AContext, scene: Scene, anchors: list[FrameSample]
) -> tuple[Phase1AMaskParams | None, list[VisionEvent]]:
    """Run circle detector on each anchor frame; majority-vote.

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
    finally:
        cap.release()

    # Emit one info event per CV candidate (not too noisy: at most 3 frames
    # per scene, typically far fewer; circle detector returns at most 1
    # per frame after the radius / minDist filters).
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
# VLM fallback — primary path for rectangle / line_split / unknown
# ---------------------------------------------------------------------------


async def _vlm_fallback(
    ctx: Phase1AContext,
    scene: Scene,
    anchors: list[FrameSample],
    parent_event_id: str | None,
) -> tuple[Phase1AMaskParams | None, list[VisionEvent]]:
    """VLM looks at first/mid/last frames as a 3-frame grid for non-circle masks."""
    settings = get_settings()
    cl = ctx.client(STAGE)
    refs = [FrameRef(ts=f.ts, url=f.rel_path, scene_idx=f.scene_idx) for f in anchors]
    messages = [
        {"role": "system", "content": load_prompt("1a_masks")},
        {
            "role": "user",
            "content": (
                f"Scene {scene.idx}（{scene.start_sec:.2f}s–{scene.end_sec:.2f}s）的"
                f"首/中/末三帧已附上。CV 圆形检测未命中，请你判断是否存在"
                "矩形 / 线分屏等其他形状的几何蒙版。"
                "再次强调：字幕 / 标题条 / 水印 / logo / UI 元素**不算几何蒙版**。"
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
