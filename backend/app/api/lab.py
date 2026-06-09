"""SubcapabilityLab — Phase 1A single-subcap exercise harness (dev-only).

Mounted only when ``ENABLE_DEV_MOCK=true`` so production builds don't
expose ad-hoc detection endpoints. The lab lets you pick an existing
sample, run one subcap against it, and watch the resulting VisionEvent
stream in the workbench.

Each subcap exposes: a ``runner`` async callable taking a single
``Phase1AContext`` (which lazily computes scenes/frames once and caches
them across subcap calls), a list of compatible fixture sample ids, and
a ``baseline`` key under ``tests/baselines.json``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app import tasks_store
from app.config import get_settings
from app.event_bus import get_event_bus
from app.extract.context import Phase1AContext
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


SubcapRunner = Callable[[Phase1AContext], Awaitable[None]]


@dataclass(frozen=True)
class SubcapDef:
    name: str
    label: str
    stage: str
    fixtures: tuple[str, ...]
    baseline_key: str
    runner: SubcapRunner


# ---------------------------------------------------------------------------
# Subcap runners — thin orchestrators that share Phase1AContext.
# Each runner just calls the underlying detect_X(ctx) — scenes / frames are
# computed lazily inside the context and cached, so a multi-subcap session
# pays the detect/sample cost once per fixture.
# ---------------------------------------------------------------------------


async def _run_scenes(ctx: Phase1AContext) -> None:
    await ctx.scenes()  # publishes scene-cut events as a side effect


async def _run_captions(ctx: Phase1AContext) -> None:
    from app.extract.captions import detect_captions

    await detect_captions(ctx)


async def _run_captions_anim(ctx: Phase1AContext) -> None:
    from app.extract.captions import detect_captions
    from app.extract.captions_anim import verify_caption_anim

    captions, _ = await detect_captions(ctx)
    frames = await ctx.frames()
    for idx, cap in enumerate(captions):
        # Match the same anchor frame the caption entity event used so the
        # CV refine event lands on the same frame in the workbench.
        anchor = (
            min(frames, key=lambda f: abs(f.ts - cap.start)) if frames else None
        )
        anchor_url = (
            f"/data/{anchor.rel_path.lstrip('/')}" if anchor is not None else None
        )
        await verify_caption_anim(
            cap,
            ctx.normalized_path,
            task_id=ctx.task_id,
            caption_idx=idx,
            anchor_frame_url=anchor_url,
        )


async def _run_stickers(ctx: Phase1AContext) -> None:
    from app.extract.stickers import detect_stickers

    await detect_stickers(ctx)


async def _run_zoom(ctx: Phase1AContext) -> None:
    from app.extract.motion import estimate_zoom_curve, judge_zoom_direction

    directions, _ = await judge_zoom_direction(ctx)
    scenes = await ctx.scenes()
    for sc in scenes:
        d = directions.get(sc.idx)
        if d is not None and d.direction != "稳定":
            await estimate_zoom_curve(ctx, sc)


async def _run_transitions(ctx: Phase1AContext) -> None:
    from app.extract.transitions import classify_transitions

    await classify_transitions(ctx)


async def _run_masks(ctx: Phase1AContext) -> None:
    from app.extract.masks import detect_masks

    await detect_masks(ctx)


async def _run_color(ctx: Phase1AContext) -> None:
    from app.extract.color import classify_color_lut

    await classify_color_lut(ctx)


async def _run_audio(ctx: Phase1AContext) -> None:
    from app.extract.audio import extract_bgm

    await extract_bgm(ctx)


async def _run_caption_function(ctx: Phase1AContext) -> None:
    from app.extract.captions import detect_captions
    from app.understand.vision import classify_caption_function

    captions, cap_events = await detect_captions(ctx)
    frames = await ctx.frames()
    parent = cap_events[0].event_id if cap_events else None
    for idx, cap in enumerate(captions):
        anchor = next((f for f in frames if cap.start <= f.ts <= cap.end), None)
        await classify_caption_function(
            cap, anchor, task_id=ctx.task_id, caption_idx=idx, parent_event_id=parent
        )


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
    # When true, ``data/samples/{fixture_id}/extracted/`` is removed before
    # the run starts. The only durable cache in the lab loop is the sampled
    # JPEGs under ``extracted/frames/`` (frame_sampler short-circuits on
    # ``Path.exists()``); VLM calls themselves are never cached. Clearing
    # extracted/ forces both scene-anchor frames and 1fps frames to be
    # re-extracted from the source mp4, which is the right thing to do
    # when normalized.mp4 changes or when debugging stale jpgs.
    force_refresh: bool = False


def _resolve_fixture_path(fixture_id: str) -> Path | None:
    """Find the runnable mp4 under data/samples/<id>/."""
    settings = get_settings()
    sample_dir = settings.data_root / "samples" / fixture_id
    for name in ("normalized.mp4", "source.mp4"):
        p = sample_dir / name
        if p.exists():
            return p
    return None


@router.post("/lab/run-subcap/{name}")
async def run_subcap(name: str, req: RunRequest, background_tasks: BackgroundTasks) -> dict:
    _require_dev()
    if name not in REGISTRY:
        raise HTTPException(404, f"unknown subcap: {name}")
    sub = REGISTRY[name]
    normalized = _resolve_fixture_path(req.fixture_id)
    if normalized is None:
        raise HTTPException(
            404,
            f"fixture {req.fixture_id} missing normalized.mp4. "
            "请先通过 /samples 上传或 CLI ingest。",
        )
    if req.force_refresh:
        # Wipe the frame-jpg + per-task jsonl cache. Source.mp4 / normalized.mp4
        # stay; only derived artifacts are removed so the next run regenerates
        # everything from scratch. Done synchronously inside the handler so
        # the BackgroundTask sees a clean slate.
        extracted = get_settings().data_root / "samples" / req.fixture_id / "extracted"
        if extracted.exists():
            try:
                shutil.rmtree(extracted)
            except OSError as e:
                log.warning("lab.force_refresh_failed", error=str(e))
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
        ctx = Phase1AContext(
            sample_id=req.fixture_id,
            normalized_path=normalized,
            task_id=task_id,
        )
        tasks_store.update_task(task_id, status="running", stage=sub.stage, progress=0.05)
        try:
            await sub.runner(ctx)
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
