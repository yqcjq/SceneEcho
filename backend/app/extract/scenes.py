"""1A-T1 · Scene cut detection (CV — PySceneDetect).

The temporal floor that VLM cannot reach: ±0.04s precision via
``ContentDetector(threshold=27)``. One ``VisionEvent`` per detected cut so
the workbench shows the timeline points lining up. Each scene appends to
``Phase1AReport.scenes``.

Scene events also carry a ``frame_url`` pointing to a *representative*
frame inside the scene (start + small offset), written to the canonical
``extracted/frames/`` dir shared with ``frame_sampler``. This satisfies
D19's "frame_url on entity events so the workbench left pane renders the
frame" — without it, scene-cut cards show "no frame" even though we know
exactly which frame represents the cut. The shared dir means
``sample_frames`` later skips re-extraction (its ``abs_path.exists()``
guard already handles idempotency).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.phase1a_report import Phase1AScene
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger

STAGE = "1A.scenes"
log = get_logger(__name__)

# Offset into the scene used to pick the representative frame. Too close to
# the cut catches the transition; too far loses "this is the cut" framing.
_ANCHOR_OFFSET_SEC = 0.1


@dataclass
class Scene:
    """In-process struct used by Phase1AContext + downstream subcaps.

    Mirrors :class:`app.ir.phase1a_report.Phase1AScene` (which is pydantic
    + JSON-Schema-exported). The dataclass version stays in ``extract`` so
    sub-modules don't need to depend on the IR layer for a 3-field record.
    """

    idx: int
    start_sec: float
    end_sec: float

    def to_report_entry(self) -> Phase1AScene:
        return Phase1AScene(idx=self.idx, start_sec=self.start_sec, end_sec=self.end_sec)


async def detect_scenes(
    normalized_path: Path,
    *,
    task_id: str,
    threshold: float = 27.0,
    frames_dir_rel: str | None = None,
) -> tuple[list[Scene], list[VisionEvent]]:
    """Run PySceneDetect's ``ContentDetector`` and emit cut events.

    When ``frames_dir_rel`` is provided (the lab + 1B pipeline path), each
    scene also gets a representative frame extracted via ffmpeg and the
    emitted event carries the matching ``frame_url``. ``Phase1AContext.scenes``
    passes ``samples/{sample_id}/extracted/frames`` here so scene frames
    land in the same dir ``sample_frames`` writes to — re-extraction by the
    later sampler is a no-op due to ``Path.exists()`` short-circuit.

    Falls back to a single-scene result + warning event when the dependency
    is missing — keeps Phase 1A unit tests green without ``[extract]``
    extras and lets the rest of the pipeline downstream not crash.
    """
    bus = get_event_bus()
    try:
        # Lazy import — in the [extract] extras only.
        from scenedetect import (  # type: ignore[import-not-found]
            ContentDetector,
            SceneManager,
            open_video,
        )
    except ImportError as e:
        log.warning("scenes.dep_missing", error=str(e))
        return await _fallback(normalized_path, task_id, str(e))

    try:
        video = open_video(str(normalized_path))
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=threshold))
        sm.detect_scenes(video=video)
        boundaries = sm.get_scene_list()
    except Exception as e:  # noqa: BLE001
        log.error("scenes.detect_failed", error=str(e))
        return await _fallback(normalized_path, task_id, str(e))

    scenes: list[Scene] = []
    events: list[VisionEvent] = []
    if not boundaries:
        # No cuts detected → single scene spanning the whole video.
        scenes.append(Scene(idx=0, start_sec=0.0, end_sec=_video_duration(normalized_path)))
    else:
        for i, (start, end) in enumerate(boundaries):
            scenes.append(Scene(idx=i, start_sec=start.get_seconds(), end_sec=end.get_seconds()))
    for s in scenes:
        # Append each Phase1AScene to Phase1AReport.scenes. Empty-length
        # scenes still emit the boundary event but skip the IR write so the
        # report doesn't carry zero-span entries that downstream slot
        # constraints would reject.
        ir_target: IRTarget | None = None
        ir_value: dict | None = None
        if s.end_sec - s.start_sec > 0:
            ir_target = IRTarget(ir_type="Phase1AReport", path="scenes", op="append")
            ir_value = s.to_report_entry().model_dump(mode="json")
        # Pick a representative frame inside the scene and pin frame_url to
        # it. ``_anchor_frame_url`` returns None on any failure (no
        # frames_dir_rel, ffmpeg missing, zero-length scene) — the event
        # still publishes; the workbench just shows "no frame" instead.
        anchor_ts, frame_url = _anchor_frame(
            normalized_path, s, frames_dir_rel=frames_dir_rel
        )
        ev = VisionEvent(
            task_id=task_id,
            source="cv",
            stage=STAGE,
            frame_ts=anchor_ts,
            frame_url=frame_url,
            semantic_label=f"切点 #{s.idx} @{s.start_sec:.2f}s",
            reasoning=(
                f"PySceneDetect ContentDetector(threshold={threshold}) 在 "
                f"{s.start_sec:.2f}s–{s.end_sec:.2f}s 标识为 scene {s.idx}。"
            ),
            confidence=0.99,
            ir_target=ir_target,
            ir_value=ir_value,
            duration_ms=0,
        )
        await bus.publish(task_id, ev)
        events.append(ev)
    return scenes, events


async def _fallback(
    normalized_path: Path, task_id: str, reason: str
) -> tuple[list[Scene], list[VisionEvent]]:
    duration = _video_duration(normalized_path)
    bus = get_event_bus()
    scene = Scene(idx=0, start_sec=0.0, end_sec=duration)
    ev = VisionEvent(
        task_id=task_id,
        source="cv",
        stage=STAGE,
        semantic_label="[fallback] 单 scene",
        reasoning=f"PySceneDetect 未就绪 / 失败：{reason}。回退为整段一个 scene。",
        confidence=0.3,
        duration_ms=0,
        severity="warning",
    )
    await bus.publish(task_id, ev)
    return [scene], [ev]


def _video_duration(path: Path) -> float:
    """Best-effort probe; returns 0.0 when ffprobe fails."""
    try:
        from app.render import ffmpeg as ffx

        info = ffx.get_media_info(path)
        return float(info.get("format", {}).get("duration", 0.0))
    except Exception:  # noqa: BLE001
        return 0.0


def _anchor_frame(
    normalized_path: Path,
    scene: Scene,
    *,
    frames_dir_rel: str | None,
) -> tuple[float | None, str | None]:
    """Extract a representative jpg for the scene; return (ts, /data/<rel>).

    Returns ``(None, None)`` when extraction is skipped (no out dir, zero
    span, or ffmpeg failure). The caller publishes the event regardless —
    a missing frame degrades the left pane to "no frame" but doesn't break
    the timeline. Idempotent: re-runs reuse existing jpgs.
    """
    if frames_dir_rel is None:
        return None, None
    span = scene.end_sec - scene.start_sec
    if span <= 0:
        return None, None
    # Pick min(start + 0.1, midpoint) so very short scenes still land inside.
    anchor_ts = round(min(scene.start_sec + _ANCHOR_OFFSET_SEC, (scene.start_sec + scene.end_sec) / 2), 2)
    settings = get_settings()
    out_rel = f"{frames_dir_rel.rstrip('/')}/{anchor_ts:.2f}.jpg"
    abs_path = settings.resolve(out_rel)
    if not abs_path.exists():
        try:
            # Local import keeps the scenes module independent of
            # frame_sampler import time (and avoids a cycle if downstream
            # code ever imports both).
            from app.extract.frame_sampler import extract_one_frame

            extract_one_frame(normalized_path, abs_path, anchor_ts)
        except Exception as e:  # noqa: BLE001
            log.warning("scenes.anchor_frame_failed", scene=scene.idx, error=str(e))
            return anchor_ts, None
    return anchor_ts, f"/data/{out_rel.lstrip('/')}"
