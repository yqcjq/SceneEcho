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


@router.get("/projects")
def list_projects() -> dict:
    """List every project on disk, newest first.

    Powers the Editor's "历史项目" entry strip. The filesystem is already
    the source of truth for project state (D2 — paths relative to
    DATA_ROOT); we scan ``projects/`` rather than introduce a parallel
    index table. Volumes are dozens of dirs at most — directory listing
    is fast enough and never falls out of sync with reality.

    Each row reports:
    - ``project_id``    — directory name (``prj_*`` or ``demo_*``)
    - ``has_ir``        — True iff ``project.json`` exists (= apply ran)
    - ``template_id``   — first section's template_id if has_ir, else None
    - ``updated_at``    — directory mtime (epoch seconds) for sort order

    Rows are returned in descending ``updated_at`` order so the most
    recently touched project shows up first in the strip.
    """
    settings = get_settings()
    root = settings.data_root / "projects"
    if not root.exists():
        return {"projects": []}
    out: list[dict] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        project_id = entry.name
        project_json = entry / "project.json"
        has_ir = project_json.exists()
        template_id: str | None = None
        if has_ir:
            # Read just enough to identify which template was applied.
            # Full IR load happens lazily on /projects/{id}.
            try:
                import json as _json

                with project_json.open("r", encoding="utf-8") as fh:
                    raw = _json.load(fh)
                sections = raw.get("sections") or []
                if sections:
                    template_id = sections[0].get("template_id") or None
            except Exception:  # noqa: BLE001
                # Corrupt project.json shouldn't break the listing.
                pass
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append(
            {
                "project_id": project_id,
                "has_ir": has_ir,
                "template_id": template_id,
                "updated_at": mtime,
            }
        )
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    return {"projects": out}


@router.post("/projects")
async def upload_project(file: UploadFile) -> dict:
    """Upload + normalize a user material clip.

    PLAN 1657: when the user uploads e.g. a 16:9 clip into a 9:16 template
    canvas, the result must be 9:16 with the original centred and a
    blurred background filling the bars (not solid black). We always pass
    ``pad_mode="blur"`` here — for matching aspect ratios the blur is a
    no-op anyway since ``force_original_aspect_ratio=decrease`` already
    fits the canvas; the boxblur path just costs a few extra filter ops.
    Sample uploads keep ``pad_mode="black"`` so the recognized stage
    isn't corrupted by a synthetic background.
    """
    settings = get_settings()
    project_id = _new_project_id()
    base = settings.data_root / "projects" / project_id
    base.mkdir(parents=True, exist_ok=True)
    src_path = base / "user_material.mp4"
    with src_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    norm_path = base / "normalized.mp4"
    try:
        info = ffx.normalize(src_path, norm_path, pad_mode="blur")
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
    # ``transcribe`` is contractually non-raising — its WhisperX path is
    # try/except'd internally and degrades to a uniform-chunk fallback +
    # warning event. So no outer try/except here.
    ledger, _ = await transcribe(normalized, task_id=task_id)

    # Persist for apply_short to reuse — the user's flow is recommend →
    # apply on the same project, both reading the same normalized.mp4. Skipping
    # the second ASR call cuts apply latency by ~one-WhisperX-load (3-5s on
    # WhisperX small / 1-2s on GLM). Stale guard isn't needed: the file is
    # 1:1 with project_id, and re-uploading creates a new project_id.
    try:
        (project_dir / "transcript.json").write_text(
            ledger.model_dump_json(indent=2), encoding="utf-8"
        )
    except OSError as e:
        log.warning("recommend.transcript_persist_failed", error=str(e))

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


@router.get("/projects/{project_id}/recommendations")
def get_recommendations(project_id: str) -> dict:
    """Replay the most recent recommend_templates task's results.

    Reads from ``tasks`` + events.jsonl rather than caching in project.json —
    events.jsonl is the single source of truth (D36). The Editor's "step 2"
    card calls this on project reload to restore the recommendation list
    after the user navigates away and comes back; the recommend POST itself
    stays unchanged.

    Returns ``{task_id: null, recommendations: []}`` when no
    recommend_templates task has run yet, so the Editor can quietly show
    the "fresh start" state without an HTTP error to handle.
    """
    from app.kb import store as kb_store

    settings = get_settings()
    if not (settings.data_root / "projects" / project_id).exists():
        raise HTTPException(404, f"project {project_id} not found")

    rows = tasks_store.list_by_resource("project", project_id)
    rec_tasks = [r for r in rows if r["kind"] == "recommend_templates"]
    if not rec_tasks:
        return {"task_id": None, "recommendations": []}
    task_id = rec_tasks[0]["id"]

    # Each recommendation was emitted as one VisionEvent stage="2.recommend"
    # with ir_value=template_id (string). The chat_vision call event itself
    # also carries stage="2.recommend" but ir_value is the structured
    # _RecommendResult dump (dict) — filter on str so we only get entity
    # rows. Fallback warnings use stage="2.recommend.fallback" and are
    # already excluded by the stage equality check.
    events = get_event_bus().replay(task_id)
    catalog: dict[str, dict] = {}
    out: list[dict] = []
    for ev in events:
        if ev.stage != "2.recommend":
            continue
        if not isinstance(ev.ir_value, str) or not ev.ir_value:
            continue
        template_id = ev.ir_value
        if template_id not in catalog:
            row = kb_store.get_template(template_id) or {}
            catalog[template_id] = row
        row = catalog[template_id]
        out.append(
            {
                "template_id": template_id,
                "score": float(ev.confidence or 0.0),
                "reason": ev.reasoning or "",
                "name": row.get("name"),
                "thumbnail_path": row.get("thumbnail_path"),
                "tags": row.get("tags"),
            }
        )
    return {
        "task_id": task_id,
        "workbench_url": f"/workbench/{task_id}",
        "recommendations": out,
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


def _aigc_cost_summary(project_id: str, ir: ProjectIR | None) -> dict | None:
    """Replay the latest apply_short task's events and aggregate AIGC cost.

    Apply runs as a background task (the POST /apply response carries only
    a task_id), so we can't return the summary in the apply response itself.
    Instead we derive it on every project load from the events.jsonl truth
    source (D36) — the same pattern as :func:`get_recommendations`.

    Returns ``None`` when the project has no AIGC activity at all (no apply
    task, no opt-in, or zero broll events) so the Editor can suppress the
    cost panel for plain non-AIGC projects.

    Shape::

        {"broll_calls": int,        # 5.aigc.broll events with cache_hit=False
         "broll_cache_hits": int,   # 5.aigc.broll events with cache_hit=True
         "broll_failures": int,     # ProjectIR.degraded keys *.aigc_broll
         "total_seconds_spent": float}  # sum of event.duration_ms / 1000
    """
    rows = tasks_store.list_by_resource("project", project_id)
    apply_tasks = [r for r in rows if r["kind"] == "apply_short"]
    if not apply_tasks:
        return None
    task_id = apply_tasks[0]["id"]
    events = get_event_bus().replay(task_id)
    broll_events = [e for e in events if e.stage == "5.aigc.broll"]
    failures = sum(
        1
        for k in (ir.degraded if ir else {})
        if k.endswith(".aigc_broll")
    )
    if not broll_events and failures == 0:
        return None
    cache_hits = sum(1 for e in broll_events if "cache_hit=True" in (e.reasoning or ""))
    fresh = len(broll_events) - cache_hits
    total_ms = sum(int(e.duration_ms or 0) for e in broll_events)
    return {
        "broll_calls": fresh,
        "broll_cache_hits": cache_hits,
        "broll_failures": failures,
        "total_seconds_spent": round(total_ms / 1000.0, 2),
    }


@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    """Return ProjectIR + AIGC cost summary (or null when apply hasn't run)."""
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
        "aigc_cost_summary": _aigc_cost_summary(project_id, ir),
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
                        "use_aigc_broll": s.use_aigc_broll,
                        "aigc_broll_path": s.aigc_broll_path,
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


# ---------------------------------------------------------------------------
# Phase 2.5: history list + lineage
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: str) -> dict:
    """Mirror of ``/samples/{id}/tasks`` for project resources.

    Used by the Editor's "本项目所有任务" listing and by the
    ``WorkbenchBreadcrumb`` to show "本项目其它任务" alongside the
    breadcrumb chain.
    """
    settings = get_settings()
    if not (settings.data_root / "projects" / project_id).exists():
        raise HTTPException(404, f"project {project_id} not found")
    rows = tasks_store.list_by_resource("project", project_id)
    return {
        "project_id": project_id,
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


@router.get("/projects/{project_id}/lineage")
def project_lineage(project_id: str) -> dict:
    """Return the apply-chain audit trail for migration visualisation.

    Returns:
    - ``template`` — the source TemplateIR (skeleton + style summary)
    - ``mapping`` — per-slot user-unit assignments + ±20% speed clamps
    - ``gaps`` — Gap list with fill_result text
    - ``placed_segments`` — final PlacedSegment chain
    - ``diff`` — fields touched by NL/panel edits since apply (read
      from the snapshot stack — a missing v{1}.json means no edits).

    The Editor's right pane shows this as a four-step strip
    (抽取 / 映射 / 缺口 / 补全 / 编辑) — directly satisfies PLAN 1701.
    """
    ir = _load_project(project_id)
    if ir is None:
        raise HTTPException(404, f"project {project_id}: project.json missing — run apply first")
    settings = get_settings()
    project_dir = settings.data_root / "projects" / project_id

    template_summary: dict | None = None
    if ir.sections and ir.sections[0].template_id:
        from app.kb import store as kb_store

        full = kb_store.get_template(ir.sections[0].template_id)
        if full:
            tir = full.get("ir") or {}
            template_summary = {
                "id": full.get("id"),
                "name": full.get("name"),
                "tags": full.get("tags"),
                "skeleton": [
                    {
                        "role": (s or {}).get("role"),
                        "duration": (s or {}).get("duration"),
                        "material_req": (s or {}).get("material_req"),
                        "caption_function": (s or {}).get("caption_function"),
                    }
                    for s in (tir.get("skeleton") or [])
                ],
                "audio": tir.get("audio"),
            }

    mapping = []
    gaps_summary: list[dict] = []
    placed: list[dict] = []
    for sec in ir.sections:
        for s in sec.segments:
            placed.append(
                {
                    "slot_role": s.slot_role,
                    "source_unit_ids": list(s.source_unit_ids),
                    "src_timerange": list(s.src_timerange),
                    "timeline_start": s.timeline_start,
                    "speed": s.speed,
                    "is_fill": s.is_fill,
                }
            )
            mapping.append(
                {
                    "slot_role": s.slot_role,
                    "source_unit_ids": list(s.source_unit_ids),
                    "src_timerange": list(s.src_timerange),
                    "speed": s.speed,
                    "is_fill": s.is_fill,
                }
            )
        for g in sec.gaps:
            gaps_summary.append(
                {
                    "slot_role": g.slot_role,
                    "reason": g.reason,
                    "fill_strategy": g.fill_strategy,
                    "fill_result": g.fill_result,
                }
            )

    # Diff: count snapshots (= number of forward edits still undo-able).
    snap_dir = project_dir / "snapshots"
    edit_count = (
        len([p for p in snap_dir.iterdir() if p.suffix == ".json"]) if snap_dir.exists() else 0
    )

    return {
        "project_id": project_id,
        "template": template_summary,
        "mapping": mapping,
        "placed_segments": placed,
        "gaps": gaps_summary,
        "captions_count": len(ir.captions),
        "bgm_track": ir.bgm_track,
        "canvas": ir.canvas,
        "version": ir.version,
        "edit_count": edit_count,
        "degraded": ir.degraded,
    }
