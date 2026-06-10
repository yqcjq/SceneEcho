"""Sample upload + Phase 0 render-demo endpoint."""

from __future__ import annotations

import shutil
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app import tasks_store
from app.config import get_settings
from app.ir.project import Caption, PlacedSegment, ProjectIR, Section
from app.ir.template import CaptionStyle, StyleRule
from app.logging import get_logger
from app.render import ffmpeg as ffx
from app.render.client import render_project

router = APIRouter()
log = get_logger(__name__)


def _new_sample_id() -> str:
    return f"smp_{uuid.uuid4().hex[:10]}"


@router.post("/samples")
async def upload_sample(file: UploadFile) -> dict:
    settings = get_settings()
    sample_id = _new_sample_id()
    base = settings.data_root / "samples" / sample_id
    base.mkdir(parents=True, exist_ok=True)
    src_path = base / "source.mp4"
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    norm_path = base / "normalized.mp4"
    try:
        info = ffx.normalize(src_path, norm_path)
    except Exception as e:  # noqa: BLE001
        log.error("normalize_failed", sample_id=sample_id, error=str(e))
        raise HTTPException(500, f"normalize failed: {e}") from e

    thumb = base / "thumbnail.jpg"
    try:
        ffx.extract_thumbnail(norm_path, thumb, at=0.1)
    except Exception as e:  # noqa: BLE001
        log.warning("thumbnail_failed", sample_id=sample_id, error=str(e))

    return {
        "sample_id": sample_id,
        "source_path": str(src_path.relative_to(settings.data_root)).replace("\\", "/"),
        "normalized_path": str(norm_path.relative_to(settings.data_root)).replace("\\", "/"),
        "info": {
            "format": info.get("format", {}),
            "streams": [
                {
                    k: s.get(k)
                    for k in (
                        "codec_type",
                        "codec_name",
                        "width",
                        "height",
                        "r_frame_rate",
                        "duration",
                    )
                }
                for s in info.get("streams", [])
            ],
        },
    }


async def _run_render(task_id: str, ir: ProjectIR) -> None:
    tasks_store.update_task(task_id, status="running", stage="render", progress=0.05)
    try:
        result = await render_project(ir, task_id=task_id)
        tasks_store.update_task(
            task_id, status="completed", progress=1.0, stage="done", result=result
        )
    except Exception as e:  # noqa: BLE001
        log.error("render_failed", task_id=task_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))


@router.post("/samples/{sample_id}/render-demo")
async def render_demo(sample_id: str, background_tasks: BackgroundTasks) -> dict:
    settings = get_settings()
    base = settings.data_root / "samples" / sample_id
    norm = base / "normalized.mp4"
    if not norm.exists():
        raise HTTPException(404, "sample normalized.mp4 not found")

    info = ffx.get_media_info(norm)
    duration = float(info.get("format", {}).get("duration", 5.0))

    project_id = f"demo_{sample_id}_{int(time.time())}"
    project_dir = settings.data_root / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    # Demo uses the sample's normalized.mp4 as the "user material" for Phase 0 only.
    user_material_rel = str(norm.relative_to(settings.data_root)).replace("\\", "/")

    ir = ProjectIR(
        project_id=project_id,
        user_material=user_material_rel,
        sections=[
            Section(
                topic="demo",
                template_id="",
                segments=[
                    PlacedSegment(
                        slot_role="主体",
                        src_timerange=(0.0, duration),
                        timeline_start=0.0,
                        applied_style=StyleRule(),
                    )
                ],
            )
        ],
        captions=[
            Caption(
                text="Hello SceneEcho",
                start=0.0,
                end=min(duration, 3.0),
                style=CaptionStyle(),
            )
        ],
        canvas={"width": 1080, "height": 1920, "fps": 30},
    )

    (project_dir / "project.json").write_text(ir.model_dump_json(indent=2), encoding="utf-8")

    task_id = tasks_store.create_task("render", resource_kind="project", resource_id=project_id)
    background_tasks.add_task(_run_render, task_id, ir)
    return {"task_id": task_id, "project_id": project_id}


# ---------------------------------------------------------------------------
# Phase 1B · extract template trigger
# ---------------------------------------------------------------------------


async def _run_extract_template(task_id: str, sample_id: str, name: str | None) -> None:
    """BackgroundTask wrapper for the extract pipeline.

    The pipeline itself never raises (every subcap goes through ``_safe``);
    this wrapper still defends with try/except in case of programmer error
    so the task entry doesn't sit in 'running' forever.
    """
    from app.event_bus import get_event_bus
    from app.extract.pipeline import extract_template

    bus = get_event_bus()
    try:
        await extract_template(sample_id, task_id, name=name)
        tasks_store.update_task(
            task_id, status="completed", progress=1.0, stage="1B.pipeline.done"
        )
    except Exception as e:  # noqa: BLE001
        log.error("extract_template_crashed", task_id=task_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
    finally:
        bus.close_task(task_id)


@router.post("/samples/{sample_id}/extract")
async def extract_template_endpoint(
    sample_id: str, background_tasks: BackgroundTasks, name: str | None = None
) -> dict:
    """Trigger Phase 1B template extraction for a previously uploaded sample.

    Returns the task id + a workbench URL so the frontend can navigate
    to ``/workbench/{task_id}`` and watch the full DAG of VisionEvents
    fire in real time. The task uses ``resource_kind=sample`` so events
    land in ``samples/{sid}/extracted/events_{task_id}.jsonl`` per the
    path-scheme B routing in ``event_bus``.
    """
    settings = get_settings()
    sample_dir = settings.data_root / "samples" / sample_id
    if not (sample_dir / "normalized.mp4").exists() and not (sample_dir / "source.mp4").exists():
        raise HTTPException(404, f"sample {sample_id} missing normalized.mp4 / source.mp4")
    task_id = tasks_store.create_task(
        "extract_template", resource_kind="sample", resource_id=sample_id
    )
    background_tasks.add_task(_run_extract_template, task_id, sample_id, name)
    return {
        "task_id": task_id,
        "sample_id": sample_id,
        "workbench_url": f"/workbench/{task_id}",
    }


# ---------------------------------------------------------------------------
# Phase 2.5 · extract history entry
# ---------------------------------------------------------------------------


@router.get("/samples/{sample_id}/tasks")
def list_sample_tasks(sample_id: str) -> dict:
    """Return every task attached to this sample, newest first.

    Powers the ``ExtractHistoryList`` widget on the sample detail page:
    the user uploads once, runs extract repeatedly, then wants to come
    back days later and reopen a specific workbench. The composite
    index added in Phase 2.5 keeps this O(log n) even at large
    histories. ``result_json`` is intentionally NOT included — the
    list view only needs metadata.
    """
    settings = get_settings()
    if not (settings.data_root / "samples" / sample_id).exists():
        raise HTTPException(404, f"sample {sample_id} not found")
    rows = tasks_store.list_by_resource("sample", sample_id)
    return {
        "sample_id": sample_id,
        "tasks": [
            {
                "task_id": r["id"],
                "kind": r["kind"],
                "status": r["status"],
                "progress": r.get("progress", 0.0),
                "stage": r.get("stage"),
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
                "error": r.get("error"),
            }
            for r in rows
        ],
    }
