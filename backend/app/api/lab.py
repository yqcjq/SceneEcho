"""SubcapabilityLab — Phase 1A single-subcap exercise harness (dev-only).

Mounted only when ``ENABLE_DEV_MOCK=true`` so production builds don't
expose ad-hoc detection endpoints. The lab lets you pick an existing
sample, run one subcap against it, and watch the resulting VisionEvent
stream in the workbench.

Each subcap exposes: a ``runner`` async callable, a list of compatible
fixture sample ids, and a ``baseline`` key to look up under
``tests/baselines.json``. The registry is the single place to add a new
subcap to the lab UI.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app import tasks_store
from app.config import get_settings
from app.event_bus import get_event_bus
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


SubcapRunner = Callable[[Path, str], Awaitable[None]]


@dataclass(frozen=True)
class SubcapDef:
    name: str  # short id, also URL slug
    label: str  # human-readable Chinese label
    stage: str  # canonical stage prefix this subcap emits
    fixtures: tuple[str, ...]  # compatible sample ids
    baseline_key: str  # path under tests/baselines.json
    runner: SubcapRunner  # async callable taking (normalized_path, task_id)


# ---------------------------------------------------------------------------
# Subcap runners — thin orchestrators that reuse the extract/* implementations.
# ---------------------------------------------------------------------------


async def _run_scenes(normalized: Path, task_id: str) -> None:
    from app.extract.scenes import detect_scenes

    await detect_scenes(normalized, task_id=task_id)


async def _run_captions(normalized: Path, task_id: str) -> None:
    from app.extract.captions import detect_captions
    from app.extract.frame_sampler import sample_frames
    from app.extract.scenes import detect_scenes

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized,
        out_dir_rel=out_dir_rel,
        task_id=task_id,
        scenes=scenes,
    )
    await detect_captions(normalized, frames, task_id=task_id)


async def _run_captions_anim(normalized: Path, task_id: str) -> None:
    from app.extract.captions import detect_captions
    from app.extract.captions_anim import verify_caption_anim
    from app.extract.frame_sampler import sample_frames
    from app.extract.scenes import detect_scenes

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    captions, _ = await detect_captions(normalized, frames, task_id=task_id)
    for cap in captions:
        await verify_caption_anim(cap, normalized, task_id=task_id)


async def _run_stickers(normalized: Path, task_id: str) -> None:
    from app.extract.frame_sampler import sample_frames
    from app.extract.scenes import detect_scenes
    from app.extract.stickers import detect_stickers

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    await detect_stickers(normalized, frames, task_id=task_id)


async def _run_zoom(normalized: Path, task_id: str) -> None:
    from app.extract.frame_sampler import sample_frames
    from app.extract.motion import estimate_zoom_curve, judge_zoom_direction
    from app.extract.scenes import detect_scenes

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    directions, _ = await judge_zoom_direction(scenes, frames, task_id=task_id)
    for sc in scenes:
        if directions.get(sc.idx) and directions[sc.idx].direction != "稳定":
            await estimate_zoom_curve(normalized, sc, task_id=task_id)


async def _run_transitions(normalized: Path, task_id: str) -> None:
    from app.extract.frame_sampler import sample_frames
    from app.extract.scenes import detect_scenes
    from app.extract.transitions import classify_transitions

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    await classify_transitions(scenes, frames, task_id=task_id)


async def _run_masks(normalized: Path, task_id: str) -> None:
    from app.extract.frame_sampler import sample_frames
    from app.extract.masks import detect_masks
    from app.extract.scenes import detect_scenes

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    await detect_masks(scenes, frames, task_id=task_id)


async def _run_color(normalized: Path, task_id: str) -> None:
    from app.extract.color import classify_color_lut
    from app.extract.frame_sampler import sample_frames
    from app.extract.scenes import detect_scenes

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    await classify_color_lut(normalized, frames, task_id=task_id)


async def _run_audio(normalized: Path, task_id: str) -> None:
    from app.extract.audio import extract_bgm

    await extract_bgm(normalized, task_id=task_id)


async def _run_caption_function(normalized: Path, task_id: str) -> None:
    from app.extract.captions import detect_captions
    from app.extract.frame_sampler import sample_frames
    from app.extract.scenes import detect_scenes
    from app.understand.vision import classify_caption_function

    scenes, _ = await detect_scenes(normalized, task_id=task_id)
    sample_id = _sample_id_from_path(normalized)
    out_dir_rel = f"samples/{sample_id}/extracted/frames"
    frames, _ = await sample_frames(
        normalized, out_dir_rel=out_dir_rel, task_id=task_id, scenes=scenes
    )
    captions, cap_events = await detect_captions(normalized, frames, task_id=task_id)
    # Each caption function call's parent_event_id is the original caption
    # entity event; we passed those through the events list, which doesn't
    # carry per-caption identity here, so we link to the call event id.
    parent = cap_events[0].event_id if cap_events else None
    for cap in captions:
        anchor_frame = next((f for f in frames if cap.start <= f.ts <= cap.end), None)
        await classify_caption_function(cap, anchor_frame, task_id=task_id, parent_event_id=parent)


# ---------------------------------------------------------------------------
# Registry — single source of truth for available subcaps.
# ---------------------------------------------------------------------------

REGISTRY: dict[str, SubcapDef] = {
    "scenes": SubcapDef(
        name="scenes",
        label="切点检测 (CV)",
        stage="1A.scenes",
        fixtures=("sample_basic_15s", "sample_fast_pace_8s"),
        baseline_key="subcap.scenes",
        runner=_run_scenes,
    ),
    "captions": SubcapDef(
        name="captions",
        label="字幕样式 + 位置 (VLM)",
        stage="1A.captions",
        fixtures=("sample_basic_15s",),
        baseline_key="subcap.captions",
        runner=_run_captions,
    ),
    "captions_anim": SubcapDef(
        name="captions_anim",
        label="字幕动画细节 (CV)",
        stage="1A.captions_anim",
        fixtures=("sample_basic_15s", "sample_no_bgm_10s"),
        baseline_key="subcap.captions_anim",
        runner=_run_captions_anim,
    ),
    "stickers": SubcapDef(
        name="stickers",
        label="贴纸检测 (VLM + CV refine)",
        stage="1A.stickers",
        fixtures=("sample_with_sticker_12s",),
        baseline_key="subcap.stickers",
        runner=_run_stickers,
    ),
    "zoom": SubcapDef(
        name="zoom",
        label="缩放方向 + 曲线 (VLM + CV)",
        stage="1A.zoom_direction",
        fixtures=("sample_basic_15s",),
        baseline_key="subcap.zoom",
        runner=_run_zoom,
    ),
    "transitions": SubcapDef(
        name="transitions",
        label="转场分类 (VLM)",
        stage="1A.transitions",
        fixtures=("sample_fast_pace_8s",),
        baseline_key="subcap.transitions",
        runner=_run_transitions,
    ),
    "masks": SubcapDef(
        name="masks",
        label="几何蒙版 (VLM)",
        stage="1A.masks",
        fixtures=("sample_with_mask_10s",),
        baseline_key="subcap.masks",
        runner=_run_masks,
    ),
    "color_lut": SubcapDef(
        name="color_lut",
        label="调色语义 (VLM + CV)",
        stage="1A.color_lut",
        fixtures=("sample_warm_lut_10s",),
        baseline_key="subcap.color_lut",
        runner=_run_color,
    ),
    "audio": SubcapDef(
        name="audio",
        label="BGM (Demucs + librosa)",
        stage="1A.audio",
        fixtures=("sample_basic_15s", "sample_no_bgm_10s"),
        baseline_key="subcap.audio",
        runner=_run_audio,
    ),
    "caption_function": SubcapDef(
        name="caption_function",
        label="字幕功能分类 (VLM, two-stage)",
        stage="1A.caption_function",
        fixtures=("sample_basic_15s", "sample_with_sticker_12s"),
        baseline_key="subcap.caption_function",
        runner=_run_caption_function,
    ),
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _require_dev() -> None:
    if not get_settings().enable_dev_mock:
        raise HTTPException(403, "ENABLE_DEV_MOCK is not set")


def _sample_id_from_path(p: Path) -> str:
    """Derive sample id from ``data/samples/{sid}/normalized.mp4`` style path."""
    parents = list(p.parents)
    for parent in parents:
        if parent.name == "samples":
            # next deeper component is the sid
            try:
                return p.relative_to(parent).parts[0]
            except ValueError:
                continue
    return p.parent.name


@router.get("/lab/subcaps")
def list_subcaps() -> dict:
    _require_dev()
    return {
        "subcaps": [
            {
                "name": s.name,
                "label": s.label,
                "stage": s.stage,
                "fixtures": list(s.fixtures),
                "baseline_key": s.baseline_key,
            }
            for s in REGISTRY.values()
        ]
    }


@router.get("/lab/baselines/{name}")
def get_baseline(name: str) -> dict:
    _require_dev()
    if name not in REGISTRY:
        raise HTTPException(404, f"unknown subcap: {name}")
    settings = get_settings()
    baselines_path = settings.data_root.parent.parent / "tests" / "baselines.json"
    if not baselines_path.exists():
        return {"baseline": None}
    try:
        data = json.loads(baselines_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("lab.baselines_parse_failed", error=str(e))
        return {"baseline": None}
    key = REGISTRY[name].baseline_key
    cur: Any = data
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return {"baseline": None}
    return {"baseline": cur}


class RunRequest(BaseModel):
    fixture_id: str
    dry_run: bool = False


@router.post("/lab/run-subcap/{name}")
async def run_subcap(name: str, req: RunRequest, background_tasks: BackgroundTasks) -> dict:
    _require_dev()
    if name not in REGISTRY:
        raise HTTPException(404, f"unknown subcap: {name}")
    sub = REGISTRY[name]
    settings = get_settings()
    sample_dir = settings.data_root / "samples" / req.fixture_id
    normalized = sample_dir / "normalized.mp4"
    if not normalized.exists():
        # Fall back to source.mp4 if user hasn't run the upload-normalize step.
        if (sample_dir / "source.mp4").exists():
            normalized = sample_dir / "source.mp4"
        else:
            raise HTTPException(
                404,
                f"fixture {req.fixture_id} missing normalized.mp4. "
                "请先通过 /samples 上传或 CLI ingest。",
            )
    task_id = tasks_store.create_task(
        f"lab_{name}", resource_kind="sample", resource_id=req.fixture_id
    )
    bus = get_event_bus()
    if req.dry_run:
        return {
            "task_id": task_id,
            "subcap": name,
            "fixture_id": req.fixture_id,
            "workbench_url": f"/workbench/{task_id}",
            "dry_run": True,
        }

    async def _runner() -> None:
        tasks_store.update_task(task_id, status="running", stage=sub.stage, progress=0.05)
        try:
            await sub.runner(normalized, task_id)
            tasks_store.update_task(
                task_id, status="completed", progress=1.0, stage=f"{sub.stage}.done"
            )
        except Exception as e:  # noqa: BLE001
            log.error("lab.runner_failed", subcap=name, error=str(e))
            tasks_store.update_task(task_id, status="failed", error=str(e))
        finally:
            bus.close_task(task_id)

    background_tasks.add_task(_runner)
    return {
        "task_id": task_id,
        "subcap": name,
        "fixture_id": req.fixture_id,
        "workbench_url": f"/workbench/{task_id}",
        "dry_run": False,
    }
