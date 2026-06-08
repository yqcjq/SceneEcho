"""Task status + renderer progress webhook."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import tasks_store

router = APIRouter()


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
