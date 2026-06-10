"""HTTP client to the Node renderer service."""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.ir.project import ProjectIR
from app.logging import get_logger

log = get_logger(__name__)


async def render_project(ir: ProjectIR, task_id: str | None = None) -> dict:
    """POST /render to the renderer. Returns {task_id, output_path} from the renderer."""
    settings = get_settings()
    url = f"{settings.renderer_url.rstrip('/')}/render"
    payload = {"project_ir": ir.model_dump(mode="json"), "task_id": task_id}
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


async def cancel_render(task_id: str) -> bool:
    """Best-effort cancel via the renderer's DELETE /render/{id}.

    Used by the Phase 2.5 render-throttle: when a project triggers a new
    render while the previous one is still pending/in-flight, supersede
    the old one. Returns True if the renderer acknowledged (200), False
    otherwise — callers don't block on cancellation guarantees, just on
    not piling up redundant queued jobs.
    """
    settings = get_settings()
    url = f"{settings.renderer_url.rstrip('/')}/render/{task_id}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.delete(url)
            return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        log.warning("renderer_cancel_failed", task_id=task_id, error=str(e))
        return False


async def renderer_health() -> bool:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{settings.renderer_url.rstrip('/')}/health")
            return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        log.warning("renderer_health_failed", error=str(e))
        return False
