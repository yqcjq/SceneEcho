"""Edit API (Phase 2.5) — NL / panel mutations of ProjectIR + undo.

Endpoints:
- ``POST /projects/{id}/edit`` body ``{instruction}`` → LLM-translated patches → apply → optional render
- ``POST /projects/{id}/panel-edit`` body ``{field, value, target?}`` → direct patches → apply → optional render
- ``POST /projects/{id}/undo`` → restore latest snapshot
- ``GET  /projects/{id}/history`` → flat list of all prior patches (from events.jsonl)

Every successful edit creates a task with ``kind`` in ``("nl_edit",
"panel_edit", "undo")`` so the workbench breadcrumb and the
``GET /projects/{id}/tasks`` listing surface them alongside extract /
apply tasks. The patches themselves are persisted as
``stage="2.5.nl_edit"`` VisionEvents on that task — no separate
patch_history.jsonl (see ``decisions/008-phase2-5-edit-storage.md``).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app import tasks_store
from app.agent.nl_edit import (
    STAGE,
    PatchApplyError,
    apply_patches,
    list_patch_history,
    nl_edit,
    panel_to_patches,
    push_snapshot,
    undo,
)
from app.agent.nl_edit import _OP_PRIMARY_PATH as _PATH_HINT
from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.project import ProjectIR
from app.ir.vision_event import IRTarget, VisionEvent
from app.logging import get_logger
from app.render.throttle import trigger_render_supersede

router = APIRouter()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_dir(project_id: str):
    return get_settings().data_root / "projects" / project_id


def _load_ir(project_id: str) -> ProjectIR | None:
    f = _project_dir(project_id) / "project.json"
    if not f.exists():
        return None
    try:
        return ProjectIR.model_validate_json(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("edit.load_failed", project_id=project_id, error=str(e))
        return None


def _save_ir(project_id: str, ir: ProjectIR) -> None:
    pdir = _project_dir(project_id)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(ir.model_dump_json(indent=2), encoding="utf-8")


async def _fetch_current_template(ir: ProjectIR) -> dict | None:
    if not ir.sections:
        return None
    tid = ir.sections[0].template_id
    if not tid:
        return None
    from app.kb import store as kb_store

    return kb_store.get_template(tid)


async def _fetch_template_catalog() -> list[dict]:
    from app.kb import store as kb_store

    return kb_store.list_templates()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class _EditBody(BaseModel):
    instruction: str
    render: bool = True


class _PanelEditBody(BaseModel):
    field: str
    value: object = None
    target: dict | None = None
    render: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/edit")
async def nl_edit_endpoint(
    project_id: str, body: _EditBody, background_tasks: BackgroundTasks
) -> dict:
    ir = _load_ir(project_id)
    if ir is None:
        raise HTTPException(404, f"project {project_id}: project.json missing — run apply first")

    task_id = tasks_store.create_task(
        "nl_edit", resource_kind="project", resource_id=project_id
    )
    tasks_store.update_task(task_id, status="running", stage=STAGE, progress=0.1)
    bus = get_event_bus()

    try:
        current_template = await _fetch_current_template(ir)
        catalog = await _fetch_template_catalog()
        patches, _ = await nl_edit(
            ir,
            body.instruction,
            task_id=task_id,
            current_template=current_template,
            available_templates=catalog,
        )
        if not patches:
            tasks_store.update_task(
                task_id, status="completed", progress=1.0, stage=f"{STAGE}.no_patch"
            )
            bus.close_task(task_id)
            return {
                "task_id": task_id,
                "workbench_url": f"/workbench/{task_id}",
                "patches_applied": 0,
                "ir": ir.model_dump(mode="json"),
                "render_task_id": None,
            }

        push_snapshot(project_id, ir)
        try:
            new_ir = apply_patches(ir, patches)
        except PatchApplyError as e:
            tasks_store.update_task(task_id, status="failed", error=str(e))
            bus.close_task(task_id)
            raise HTTPException(400, f"patch apply rejected: {e}") from e
        _save_ir(project_id, new_ir)

        await _emit_apply_done(task_id, len(patches), new_ir)
        render_task_id = await _maybe_kick_render(
            project_id, new_ir, render=body.render, background_tasks=background_tasks
        )
        tasks_store.update_task(
            task_id, status="completed", progress=1.0, stage=f"{STAGE}.done"
        )
        return {
            "task_id": task_id,
            "workbench_url": f"/workbench/{task_id}",
            "patches_applied": len(patches),
            "ir": new_ir.model_dump(mode="json"),
            "render_task_id": render_task_id,
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.error("edit.crashed", project_id=project_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
        raise HTTPException(500, f"edit failed: {e}") from e
    finally:
        bus.close_task(task_id)


@router.post("/projects/{project_id}/panel-edit")
async def panel_edit_endpoint(
    project_id: str, body: _PanelEditBody, background_tasks: BackgroundTasks
) -> dict:
    ir = _load_ir(project_id)
    if ir is None:
        raise HTTPException(404, f"project {project_id}: project.json missing — run apply first")
    patches = panel_to_patches(body.field, body.value, target=body.target)
    if not patches:
        raise HTTPException(400, f"panel field unknown or unsupported: {body.field}")

    task_id = tasks_store.create_task(
        "panel_edit", resource_kind="project", resource_id=project_id
    )
    tasks_store.update_task(task_id, status="running", stage=STAGE, progress=0.5)
    bus = get_event_bus()

    try:
        push_snapshot(project_id, ir)
        new_ir = apply_patches(ir, patches)
        _save_ir(project_id, new_ir)
        # Panel edits do not call the LLM; we still emit one VisionEvent per
        # patch so the workbench's patch history view picks them up via the
        # same stage filter used for NL edits.
        for patch in patches:
            ev = VisionEvent(
                task_id=task_id,
                source="system",
                stage=STAGE,
                semantic_label=f"参数面板 · {body.field}",
                reasoning=f"panel field={body.field} target={body.target} value={body.value}",
                confidence=1.0,
                ir_target=IRTarget(
                    ir_type="ProjectIR",
                    path=_target_path_hint(patch.op),
                ),
                ir_value=patch.model_dump(mode="json"),
            )
            await bus.publish(task_id, ev)
        await _emit_apply_done(task_id, len(patches), new_ir)

        render_task_id = await _maybe_kick_render(
            project_id, new_ir, render=body.render, background_tasks=background_tasks
        )
        tasks_store.update_task(
            task_id, status="completed", progress=1.0, stage=f"{STAGE}.done"
        )
        return {
            "task_id": task_id,
            "workbench_url": f"/workbench/{task_id}",
            "patches_applied": len(patches),
            "ir": new_ir.model_dump(mode="json"),
            "render_task_id": render_task_id,
        }
    except PatchApplyError as e:
        tasks_store.update_task(task_id, status="failed", error=str(e))
        raise HTTPException(400, f"patch apply rejected: {e}") from e
    except Exception as e:  # noqa: BLE001
        log.error("panel_edit.crashed", project_id=project_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
        raise HTTPException(500, f"panel-edit failed: {e}") from e
    finally:
        bus.close_task(task_id)


class _UndoBody(BaseModel):
    render: bool = True


@router.post("/projects/{project_id}/undo")
async def undo_endpoint(
    project_id: str,
    background_tasks: BackgroundTasks,
    body: _UndoBody | None = None,
) -> dict:
    restored = undo(project_id)
    if restored is None:
        raise HTTPException(400, "no snapshots to undo — project is at its initial state")
    task_id = tasks_store.create_task(
        "undo", resource_kind="project", resource_id=project_id
    )
    bus = get_event_bus()
    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="system",
            stage=STAGE,
            semantic_label=f"undo · 回到 ProjectIR.version={restored.version}",
            reasoning=(
                f"快照栈出栈最新一条；ProjectIR 写回 version={restored.version}。"
                "patch_history 中的对应正向 patch 仍在 events.jsonl 里，"
                "但 ProjectIR 已是回退后的形态。"
            ),
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="version"),
            ir_value={"op": "undo", "version": restored.version},
        ),
    )
    render = body.render if body else True
    render_task_id = await _maybe_kick_render(
        project_id, restored, render=render, background_tasks=background_tasks
    )
    tasks_store.update_task(
        task_id, status="completed", progress=1.0, stage=f"{STAGE}.undo_done"
    )
    bus.close_task(task_id)
    return {
        "task_id": task_id,
        "workbench_url": f"/workbench/{task_id}",
        "ir": restored.model_dump(mode="json"),
        "render_task_id": render_task_id,
    }


@router.get("/projects/{project_id}/history")
def history_endpoint(project_id: str) -> dict:
    return {"project_id": project_id, "patches": list_patch_history(project_id)}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _emit_apply_done(task_id: str, patch_count: int, ir: ProjectIR) -> None:
    bus = get_event_bus()
    await bus.publish(
        task_id,
        VisionEvent(
            task_id=task_id,
            source="system",
            stage=f"{STAGE}.apply_done",
            semantic_label=f"应用 {patch_count} 个 patch · ProjectIR v{ir.version}",
            reasoning=f"patches_applied={patch_count}；新版本号 {ir.version}；project.json 已落盘。",
            confidence=1.0,
            ir_target=IRTarget(ir_type="ProjectIR", path="version"),
            ir_value=ir.version,
        ),
    )


async def _maybe_kick_render(
    project_id: str,
    ir: ProjectIR,
    *,
    render: bool,
    background_tasks: BackgroundTasks,
) -> str | None:
    if not render:
        return None
    render_task = tasks_store.create_task(
        "render", resource_kind="project", resource_id=project_id
    )
    # Use BackgroundTasks so the HTTP response returns immediately; the
    # supersede + render await happen out of band.
    background_tasks.add_task(trigger_render_supersede, project_id, render_task, ir)
    return render_task


def _target_path_hint(op: str) -> str:
    return _PATH_HINT.get(op, "project_id")