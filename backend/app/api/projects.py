"""Projects API — Phase 0 upload + Phase 2 ★MVP closed loop.

Endpoints (Phase 2 additions):
- ``POST /projects``                       upload user material → normalize (existing)
- ``POST /projects/{id}/recommend-templates`` VLM top-k template recommendation
- ``POST /projects/{id}/apply``            run apply_short → write project.json
- ``GET  /projects/{id}``                  return ProjectIR + task summary
- ``POST /projects/{id}/render``           kick off renderer with ProjectIR
- ``GET  /projects/{id}/preview-props``    minimal props for ``<RemotionPlayer>``
- ``POST /projects/{id}/mix-bgm``          dev hook: mix BGM into ProjectIR's bgm_track
"""

from __future__ import annotations

import shutil
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from app import tasks_store
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.ledger import TranscriptLedger
from app.ir.project import ProjectIR
from app.logging import get_logger
from app.render import ffmpeg as ffx
from app.render.client import render_project

router = APIRouter()
log = get_logger(__name__)


def _new_project_id() -> str:
    return f"prj_{uuid.uuid4().hex[:10]}"


def _load_project(project_id: str) -> ProjectIR | None:
    s = get_settings()
    f = s.data_root / "projects" / project_id / "project.json"
    if not f.exists():
        return None
    try:
        return ProjectIR.model_validate_json(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Phase 0 (existing): upload + normalize
# ---------------------------------------------------------------------------


@router.post("/projects")
async def upload_project(file: UploadFile) -> dict:
    settings = get_settings()
    project_id = _new_project_id()
    base = settings.data_root / "projects" / project_id
    base.mkdir(parents=True, exist_ok=True)
    src_path = base / "user_material.mp4"
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    norm_path = base / "normalized.mp4"
    try:
        info = ffx.normalize(src_path, norm_path)
    except Exception as e:  # noqa: BLE001
        log.error("project_normalize_failed", project_id=project_id, error=str(e))
        raise HTTPException(500, f"normalize failed: {e}") from e

    return {
        "project_id": project_id,
        "user_material_path": str(src_path.relative_to(settings.data_root)).replace(
            "\\", "/"
        ),
        "normalized_path": str(norm_path.relative_to(settings.data_root)).replace(
            "\\", "/"
        ),
        "info": info.get("format", {}),
    }


# ---------------------------------------------------------------------------
# Phase 2: recommend / apply / render
# ---------------------------------------------------------------------------


class _RecommendBody(BaseModel):
    k: int = 3


@router.post("/projects/{project_id}/recommend-templates")
async def recommend_templates_endpoint(
    project_id: str,
    body: _RecommendBody | None = None,
) -> dict:
    """Trigger VLM template recommendation (sync, no BackgroundTask).

    Recommendation runs ASR + a single VLM call; for a 10-20s clip this
    is fast enough that the Editor calls it synchronously and parses
    the result. Background-task path would force the Editor to poll
    just for a list of three recommendations — unnecessary friction.
    """
    from app.kb import store as kb_store
    from app.kb.recommend import recommend_templates
    from app.understand.asr import transcribe

    settings = get_settings()
    project_dir = settings.data_root / "projects" / project_id
    normalized = project_dir / "normalized.mp4"
    if not normalized.exists():
        normalized = project_dir / "user_material.mp4"
    if not normalized.exists():
        raise HTTPException(404, f"project {project_id}: no normalized.mp4 / user_material.mp4")

    kb_rows = kb_store.list_templates()
    # Hydrate ir for each row so the prompt can show skeleton snapshots.
    hydrated = []
    for r in kb_rows:
        full = kb_store.get_template(r["id"]) or r
        hydrated.append(full)

    # We need a task_id so the recommendation's VisionEvents land somewhere
    # the workbench can replay. Use resource_kind="project" — events flow
    # to projects/{id}/pipeline/events_{task_id}.jsonl.
    task_id = tasks_store.create_task(
        "recommend_templates", resource_kind="project", resource_id=project_id
    )
    tasks_store.update_task(task_id, status="running", stage="2.recommend", progress=0.1)

    # ASR is the input; the events also surface in the workbench.
    try:
        ledger, _ = await transcribe(normalized, task_id=task_id)
    except Exception as e:  # noqa: BLE001
        log.error("recommend.asr_failed", project_id=project_id, error=str(e))
        ledger = TranscriptLedger(units=[], language="zh", media_path=str(normalized))

    # Sample a few frames for the VLM — re-use the extract pipeline's
    # frame sampler so we get first / mid / last.
    sample_frames: list[tuple[float, str]] = []
    try:
        from app.extract.frame_sampler import sample_frames as _do_sample
        from app.extract.scenes import detect_scenes

        scenes, _ = await detect_scenes(
            normalized,
            task_id=task_id,
            frames_dir_rel=f"projects/{project_id}/pipeline/frames",
        )
        frames, _ = await _do_sample(
            normalized,
            out_dir_rel=f"projects/{project_id}/pipeline/frames",
            task_id=task_id,
            scenes=scenes,
        )
        if frames:
            n = len(frames)
            picks = [frames[0], frames[n // 2], frames[-1]]
            sample_frames = [(f.ts, f.rel_path) for f in picks]
    except Exception as e:  # noqa: BLE001
        log.warning("recommend.frame_sample_failed", error=str(e))

    k = (body.k if body else 3) or 3
    try:
        recs, _ = await recommend_templates(
            material_path=normalized,
            ledger=ledger,
            kb_rows=hydrated,
            task_id=task_id,
            k=k,
            sample_frames=sample_frames,
        )
    except Exception as e:  # noqa: BLE001
        log.error("recommend.failed", error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
        get_event_bus().close_task(task_id)
        raise HTTPException(500, f"recommend failed: {e}") from e

    tasks_store.update_task(task_id, status="completed", progress=1.0, stage="2.recommend.done")
    get_event_bus().close_task(task_id)

    # Render the recommendations as JSON for the Editor UI.
    catalog_by_id = {r["id"]: r for r in hydrated}
    out_list = []
    for rec in recs:
        row = catalog_by_id.get(rec.template_id)
        out_list.append(
            {
                "template_id": rec.template_id,
                "score": rec.score,
                "reason": rec.reason,
                "name": (row or {}).get("name"),
                "thumbnail_path": (row or {}).get("thumbnail_path"),
                "tags": (row or {}).get("tags"),
            }
        )
    return {
        "task_id": task_id,
        "workbench_url": f"/workbench/{task_id}",
        "recommendations": out_list,
    }


class _ApplyBody(BaseModel):
    template_id: str
    allow_aigc_broll: bool = False


async def _run_apply(
    task_id: str, project_id: str, template_id: str, allow_aigc_broll: bool
) -> None:
    from app.apply.pipeline import apply_short

    bus = get_event_bus()
    try:
        await apply_short(
            project_id, template_id, task_id=task_id, allow_aigc_broll=allow_aigc_broll
        )
        tasks_store.update_task(
            task_id, status="completed", progress=1.0, stage="2.pipeline.done"
        )
    except Exception as e:  # noqa: BLE001
        log.error("apply.crashed", task_id=task_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
    finally:
        bus.close_task(task_id)


@router.post("/projects/{project_id}/apply")
async def apply_endpoint(
    project_id: str, body: _ApplyBody, background_tasks: BackgroundTasks
) -> dict:
    """Run the Phase 2 apply pipeline as a background task."""
    settings = get_settings()
    project_dir = settings.data_root / "projects" / project_id
    if not project_dir.exists():
        raise HTTPException(404, f"project {project_id} not found")
    task_id = tasks_store.create_task(
        "apply_short", resource_kind="project", resource_id=project_id
    )
    background_tasks.add_task(
        _run_apply, task_id, project_id, body.template_id, body.allow_aigc_broll
    )
    return {
        "task_id": task_id,
        "project_id": project_id,
        "workbench_url": f"/workbench/{task_id}",
    }


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    """Return ProjectIR (or null if apply hasn't run yet)."""
    ir = _load_project(project_id)
    settings = get_settings()
    project_dir = settings.data_root / "projects" / project_id
    if not project_dir.exists():
        raise HTTPException(404, f"project {project_id} not found")
    user_material_rel: str | None = None
    for candidate in ("normalized.mp4", "user_material.mp4"):
        p = project_dir / candidate
        if p.exists():
            user_material_rel = str(p.relative_to(settings.data_root)).replace("\\", "/")
            break
    return {
        "project_id": project_id,
        "ir": ir.model_dump(mode="json") if ir else None,
        "user_material_url": (
            f"/data/{user_material_rel}" if user_material_rel else None
        ),
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


@router.post("/projects/{project_id}/render")
async def render_endpoint(
    project_id: str, background_tasks: BackgroundTasks
) -> dict:
    """Kick off Remotion render of the saved ProjectIR."""
    ir = _load_project(project_id)
    if ir is None:
        raise HTTPException(404, f"project {project_id}: project.json missing — run apply first")
    task_id = tasks_store.create_task(
        "render", resource_kind="project", resource_id=project_id
    )
    background_tasks.add_task(_run_render, task_id, ir)
    return {"task_id": task_id, "project_id": project_id}


@router.get("/projects/{project_id}/preview-props")
async def preview_props(project_id: str) -> dict:
    """Minimal props the frontend's <RemotionPlayer> needs (PLAN 1619).

    Excludes degraded / sanity_check / source unit ids — the player only
    needs canvas / segments / captions / bgm_track / userMaterialUrl.
    """
    ir = _load_project(project_id)
    if ir is None:
        raise HTTPException(404, f"project {project_id}: project.json missing — run apply first")
    settings = get_settings()
    project_dir = settings.data_root / "projects" / project_id
    user_material_url: str | None = None
    for candidate in ("normalized.mp4", "user_material.mp4"):
        p = project_dir / candidate
        if p.exists():
            user_material_url = f"/data/projects/{project_id}/{candidate}"
            break
    bgm_url = None
    if ir.bgm_track:
        bgm_url = f"/data/{ir.bgm_track.lstrip('/')}"
    return {
        "project_id": project_id,
        "canvas": ir.canvas,
        "sections": [
            {
                "topic": sec.topic,
                "template_id": sec.template_id,
                "segments": [
                    {
                        "slot_role": s.slot_role,
                        "src_timerange": s.src_timerange,
                        "timeline_start": s.timeline_start,
                        "speed": s.speed,
                        "is_fill": s.is_fill,
                        "applied_style": s.applied_style.model_dump(mode="json"),
                    }
                    for s in sec.segments
                ],
            }
            for sec in ir.sections
        ],
        "captions": [c.model_dump(mode="json") for c in ir.captions],
        "user_material_url": user_material_url,
        "bgm_url": bgm_url,
    }


# ---------------------------------------------------------------------------
# Dev: BGM mixing (PLAN 1611). Most consumers don't need this directly —
# the renderer plays bgm_track alongside the user-material video and FFmpeg
# does the sidechain ducking on demand. Exposed here so /lab can A/B the
# mix without touching the renderer pipeline.
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/mix-bgm")
async def mix_bgm_endpoint(project_id: str) -> dict:
    ir = _load_project(project_id)
    if ir is None:
        raise HTTPException(404, f"project {project_id}: project.json missing")
    if not ir.bgm_track:
        raise HTTPException(400, "project has no bgm_track to mix")
    settings = get_settings()
    project_dir = settings.data_root / "projects" / project_id
    voice = project_dir / "voice.wav"
    bgm_abs = settings.resolve(ir.bgm_track)
    if not bgm_abs.exists():
        raise HTTPException(404, f"bgm_track {ir.bgm_track} not on disk")
    # Extract voice from the user material first
    src_video = project_dir / "normalized.mp4"
    if not src_video.exists():
        src_video = project_dir / "user_material.mp4"
    try:
        ffx.extract_audio(src_video, voice)
        out = project_dir / "bgm_ducked.aac"
        ffx.mix_bgm(voice, bgm_abs, out, is_instrumental=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"mix_bgm failed: {e}") from e
    rel = str(out.relative_to(settings.data_root)).replace("\\", "/")
    # Update ProjectIR so the renderer picks the ducked mix.
    ir.bgm_track = rel
    (project_dir / "project.json").write_text(ir.model_dump_json(indent=2), encoding="utf-8")
    return {"bgm_track": rel}
