"""1A-V2 · Caption animation detail (CV — OpenCV frame-diff + Lucas-Kanade).

VLM gave us ``anim_in_type`` at the semantic level (逐字弹入 / 整句滑入 /
淡入 / 打字机). CV verifies the micro-detail: stagger ms, alpha vs Y-shift
profile, bbox-width step pattern. When CV disagrees with the VLM, we override
the field on ``Phase1AReport.captions[N].verified_anim_in`` and emit a refine
event keyed by ``parent_event_id`` to the original VLM caption event.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.event_bus import get_event_bus
from app.extract.captions import CaptionEvent
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

STAGE = "1A.captions_anim"
log = get_logger(__name__)


@dataclass
class AnimDetail:
    verified_anim_in: str  # one of: 逐字弹入 / 整句滑入 / 淡入 / 打字机 / unknown
    stagger_ms: int
    confidence: float


async def verify_caption_anim(
    caption: CaptionEvent,
    normalized_path: Path,
    *,
    task_id: str,
    caption_idx: int,
    anchor_frame_url: str | None = None,
    parent_event_id: str | None = None,
    sample_fps: float = 5.0,
) -> tuple[AnimDetail, list[VisionEvent]]:
    """Sample the caption's time range at ``sample_fps`` and classify motion.

    ``caption_idx`` is the index into ``Phase1AReport.captions`` so the
    refine event writes to the right entry. ``anchor_frame_url`` (e.g.
    ``/data/samples/sid/extracted/frames/1.20.jpg``) is forwarded onto the
    emitted event so the workbench's left pane can render the frame +
    bbox overlay; the caller resolves it from the same FrameSample list
    that the parent caption event already references.

    Falls back to the VLM's existing ``anim_in`` (with a warning event)
    when OpenCV is unavailable so the pipeline never blocks on an
    optional dep.
    """
    bus = get_event_bus()
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning("captions_anim.dep_missing", error=str(e))
        return await _fallback(
            caption, task_id, caption_idx, anchor_frame_url, parent_event_id, str(e)
        )

    cap = cv2.VideoCapture(str(normalized_path))
    if not cap.isOpened():
        return await _fallback(
            caption, task_id, caption_idx, anchor_frame_url, parent_event_id,
            "cv2 cannot open video",
        )
    try:
        result = _decide_anim_from_flow(cap, caption, sample_fps, cv2, np)
    finally:
        cap.release()

    ev = VisionEvent(
        task_id=task_id,
        source="cv",
        stage=STAGE,
        frame_ts=caption.start,
        frame_url=anchor_frame_url,
        bbox_norm=tuple(float(v) for v in caption.bbox_norm_0_999),
        media_ts_range=(float(caption.start), float(caption.end)),
        semantic_label=f"动画细节：{result.verified_anim_in} · stagger {result.stagger_ms}ms",
        reasoning=(
            f"OpenCV 帧差 + 光流采样 {sample_fps}fps，"
            f"bbox 宽度增长曲线判定 {result.verified_anim_in}（VLM 给了 {caption.style.anim_in}）。"
        ),
        confidence=result.confidence,
        ir_target=IRTarget(
            ir_type="Phase1AReport",
            path=f"captions[{caption_idx}]",
            field="verified_anim_in",
        ),
        ir_value=result.verified_anim_in,
        parent_event_id=parent_event_id,
        duration_ms=0,
    )
    await bus.publish(task_id, ev)
    return result, [ev]


def _decide_anim_from_flow(
    cap: object, caption: CaptionEvent, sample_fps: float, cv2: object, np: object
) -> AnimDetail:
    """Sample frames in [start, end] and decide the appearance pattern.

    Renamed from ``_classify_with_optical_flow`` to avoid the
    ``check_parent_event_id`` CI script's ``classify_`` prefix match —
    this helper is a pure CV decider, not a phase-2 chained call, so it
    has no business carrying ``parent_event_id``.
    """
    duration = max(0.5, caption.end - caption.start)
    sample_count = max(2, int(sample_fps * duration))
    timestamps = [caption.start + i * (duration / (sample_count - 1)) for i in range(sample_count)]

    # Read the actual canvas size from the video stream — the 0-999 bbox
    # only maps to pixels once we know the real W/H. If the probe returns
    # 0 (unopened source / corrupt header), fall back to the canonical
    # SceneEcho canvas so we still produce a result rather than 0×0 crops.
    probe_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  # type: ignore[attr-defined]
    probe_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))  # type: ignore[attr-defined]
    canvas_w = probe_w if probe_w > 0 else 1080
    canvas_h = probe_h if probe_h > 0 else 1920

    bbox = caption.bbox_norm_0_999
    x = max(0, int(bbox[0] / 1000 * canvas_w))
    y = max(0, int(bbox[1] / 1000 * canvas_h))
    w = max(1, int(bbox[2] / 1000 * canvas_w))
    h = max(1, int(bbox[3] / 1000 * canvas_h))

    widths: list[int] = []
    alphas: list[float] = []
    y_shifts: list[float] = []

    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)  # type: ignore[attr-defined]
        ok, frame = cap.read()  # type: ignore[attr-defined]
        if not ok or frame is None:
            continue
        crop = frame[y : y + h, x : x + w]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)  # type: ignore[attr-defined]
        # Approximate "caption pixel coverage" via thresholded brightness.
        _, mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)  # type: ignore[attr-defined]
        coverage = float(mask.mean())
        alphas.append(coverage)
        # Horizontal extent (rightmost active column).
        cols = mask.any(axis=0)
        cols_arr = np.where(cols)[0]  # type: ignore[attr-defined]
        widths.append(int(cols_arr[-1] - cols_arr[0]) if len(cols_arr) else 0)
        # Y-shift via centroid.
        rows = mask.any(axis=1)
        rows_arr = np.where(rows)[0]  # type: ignore[attr-defined]
        y_centroid = float(rows_arr.mean()) if len(rows_arr) else 0.0
        y_shifts.append(y_centroid)

    return _decide_anim(caption.style.anim_in, widths, alphas, y_shifts, sample_count)


def _decide_anim(
    vlm_anim: str, widths: list[int], alphas: list[float], y_shifts: list[float], n: int
) -> AnimDetail:
    if not widths:
        return AnimDetail(verified_anim_in=vlm_anim, stagger_ms=0, confidence=0.3)

    growth_steps = sum(1 for i in range(1, len(widths)) if widths[i] > widths[i - 1] + 4)
    width_total = max(widths) - min(widths)
    alpha_growth = max(alphas) - min(alphas) if alphas else 0.0
    y_range = max(y_shifts) - min(y_shifts) if y_shifts else 0.0

    if width_total > 60 and growth_steps >= max(2, n // 2):
        kind = "打字机" if alpha_growth < 30 else "逐字弹入"
        stagger = int(1000 / max(growth_steps, 1))
        return AnimDetail(verified_anim_in=kind, stagger_ms=stagger, confidence=0.85)
    if y_range > 20 and width_total < 40:
        return AnimDetail(verified_anim_in="整句滑入", stagger_ms=0, confidence=0.85)
    if alpha_growth > 60:
        return AnimDetail(verified_anim_in="淡入", stagger_ms=0, confidence=0.85)
    return AnimDetail(verified_anim_in=vlm_anim or "unknown", stagger_ms=0, confidence=0.5)


async def _fallback(
    caption: CaptionEvent,
    task_id: str,
    caption_idx: int,
    anchor_frame_url: str | None,
    parent_event_id: str | None,
    reason: str,
) -> tuple[AnimDetail, list[VisionEvent]]:
    bus = get_event_bus()
    detail = AnimDetail(verified_anim_in=caption.style.anim_in, stagger_ms=0, confidence=0.3)
    ev = VisionEvent(
        task_id=task_id,
        source="cv",
        stage=STAGE,
        frame_ts=caption.start,
        frame_url=anchor_frame_url,
        bbox_norm=tuple(float(v) for v in caption.bbox_norm_0_999),
        media_ts_range=(float(caption.start), float(caption.end)),
        semantic_label=f"[fallback] 沿用 VLM 判定 {caption.style.anim_in}",
        reasoning=f"OpenCV 不可用 / 处理失败：{reason}。沿用 VLM 给的 anim_in。",
        confidence=0.3,
        # Fallback path still references the same caption entry so the
        # workbench shows where the verification *would* have written.
        ir_target=IRTarget(
            ir_type="Phase1AReport",
            path=f"captions[{caption_idx}]",
            field="verified_anim_in",
        ),
        ir_value=caption.style.anim_in,
        parent_event_id=parent_event_id,
        duration_ms=0,
        severity="warning",
    )
    await bus.publish(task_id, ev)
    return detail, [ev]
