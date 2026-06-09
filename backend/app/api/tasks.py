"""Task status + renderer progress webhook."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import tasks_store
from app.config import get_settings

router = APIRouter()


# resource_kind → DATA_ROOT subdirectory containing normalized.mp4.
# Keep the mapping declarative — adding a new resource kind only touches this
# table. Unknown kinds fall through to ``None`` (no media URL).
_RESOURCE_DIRS: dict[str, str] = {"sample": "samples", "project": "projects"}


def _resolve_normalized_media_url(task: dict) -> str | None:
    """Map a task row to its normalized.mp4 ``/data/`` URL, if one exists.

    The route returns a static URL string (not a file path) so the browser
    can drop it straight into ``<video src>``. We confirm the file exists
    on disk before advertising it — surfacing a 404-bound URL would make
    the workbench's video toggle appear broken for sample-less tasks
    (mock streams / lab runs against deleted fixtures).
    """
    kind = task.get("resource_kind")
    rid = task.get("resource_id")
    if not kind or not rid:
        return None
    subdir = _RESOURCE_DIRS.get(kind)
    if not subdir:
        return None
    settings = get_settings()
    media_path = settings.data_root / subdir / rid / "normalized.mp4"
    if not media_path.exists():
        return None
    return f"/data/{subdir}/{rid}/normalized.mp4"


class ProgressPayload(BaseModel):
    task_id: str
    progress: float
    stage: str | None = None
    status: str | None = None
    result: dict | None = None
    error: str | None = None


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    t = tasks_store.get_task(task_id)
    if not t:
        raise HTTPException(404, "task not found")
    t["normalized_media_url"] = _resolve_normalized_media_url(t)
    return t


@router.post("/internal/task-progress")
def task_progress(payload: ProgressPayload) -> dict:
    tasks_store.update_task(
        payload.task_id,
        progress=payload.progress,
        stage=payload.stage,
        status=payload.status,
        result=payload.result,
        error=payload.error,
    )
    return {"ok": True}
