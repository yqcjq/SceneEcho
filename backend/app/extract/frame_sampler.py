"""1A-T2 · Key-frame sampler.

Writes JPEGs to ``data/{kind}/{id}/extracted/frames/{ts}.jpg`` so every
downstream VLM call + the workbench's left pane share the same image
references. Sampling strategy:
- 1 fps global baseline so we always have something to look at.
- Around each scene cut: extra frame at ``cut_ts ± 0.2s`` (vetting cut
  precision in the workbench).
- Optional first / mid / last per scene for the zoom-direction call site.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.scenes import Scene
from app.ir.vision_event import VisionEvent
from app.logging import get_logger
from app.render.ffmpeg import ffmpeg_bin, get_media_info

STAGE = "1A.frames"
log = get_logger(__name__)


@dataclass
class FrameSample:
    ts: float
    rel_path: str  # DATA_ROOT-relative POSIX
    scene_idx: int | None


async def sample_frames(
    normalized_path: Path,
    *,
    out_dir_rel: str,
    task_id: str,
    scenes: Sequence[Scene] | None = None,
    fps_global: float = 1.0,
    around_cut_offset: float = 0.2,
    include_scene_anchors: bool = True,
) -> tuple[list[FrameSample], list[VisionEvent]]:
    """Sample JPEGs to ``out_dir_rel`` and return ``[FrameSample]``.

    ``out_dir_rel`` is DATA_ROOT-relative (e.g.
    ``samples/{sid}/extracted/frames``); this function creates it if needed.
    """
    settings = get_settings()
    out_dir = settings.resolve(out_dir_rel)
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = float(get_media_info(normalized_path).get("format", {}).get("duration", 0.0))
    if duration <= 0.0:
        log.warning("frames.zero_duration", path=str(normalized_path))
        return [], []

    timestamps: set[float] = set()
    # Baseline 1 fps grid.
    t = 0.0
    step = max(0.05, 1.0 / fps_global)
    while t < duration:
        timestamps.add(round(t, 2))
        t += step
    # Scene anchors.
    if scenes and include_scene_anchors:
        for s in scenes:
            if 0 < s.start_sec < duration:
                timestamps.add(round(s.start_sec - around_cut_offset, 2))
                timestamps.add(round(s.start_sec + around_cut_offset, 2))
            mid = (s.start_sec + s.end_sec) / 2
            if 0 <= mid < duration:
                timestamps.add(round(mid, 2))

    sorted_ts = sorted(t for t in timestamps if 0 <= t < duration)
    samples: list[FrameSample] = []
    for ts in sorted_ts:
        rel = f"{out_dir_rel.rstrip('/')}/{ts:.2f}.jpg"
        abs_path = settings.resolve(rel)
        if not abs_path.exists():
            try:
                _extract_frame(normalized_path, abs_path, ts)
            except Exception as e:  # noqa: BLE001
                log.warning("frames.extract_failed", ts=ts, error=str(e))
                continue
        samples.append(
            FrameSample(ts=ts, rel_path=rel, scene_idx=_scene_idx_for(ts, scenes)),
        )

    bus = get_event_bus()
    summary = VisionEvent(
        task_id=task_id,
        source="system",
        stage=STAGE,
        semantic_label=f"采样 {len(samples)} 帧",
        reasoning=(
            f"按 fps_global={fps_global} + scene 边界 ±{around_cut_offset}s 抽样，"
            f"输出到 {out_dir_rel}/。"
        ),
        confidence=1.0,
        duration_ms=0,
    )
    await bus.publish(task_id, summary)
    return samples, [summary]


def _extract_frame(src: Path, dst: Path, at: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-ss",
        f"{at:.2f}",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def _scene_idx_for(ts: float, scenes: Sequence[Scene] | None) -> int | None:
    if not scenes:
        return None
    for s in scenes:
        if s.start_sec <= ts < s.end_sec:
            return s.idx
    return scenes[-1].idx if scenes else None
