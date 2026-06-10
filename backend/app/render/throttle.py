"""Project-level render throttling (Phase 2.5).

Phase 2.5 introduces NL / panel edits that retrigger a render after every
patch (PLAN 1680). Without throttling, three NL edits 100ms apart would
queue three full renders behind each other — the user only ever cares
about the most recent one. The renderer queue is single-worker so the
older renders would just waste Chromium time before being thrown away.

This module owns a single asyncio-protected dict mapping
``project_id → in_flight_task_id`` and a public coroutine
:func:`trigger_render_supersede` that:

1. Acquires the lock for this project_id;
2. If a prior task is still in-flight, fires renderer ``DELETE /render/{tid}``
   (renderer dequeues pending; tags running as cancelled);
3. Marks our new task as the in-flight one and kicks the BackgroundTask
   that posts to renderer ``POST /render``.

No new ``app/agent/render_queue.py`` module — PLAN's design suggested one
but a 30-line dict + lock here does the same job without an extra
abstraction layer. See ``decisions/008-phase2-5-edit-storage.md``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app import tasks_store
from app.ir.project import ProjectIR
from app.logging import get_logger
from app.render.client import cancel_render, render_project

log = get_logger(__name__)

# project_id → currently-in-flight render task_id (None when idle).
_in_flight: dict[str, str | None] = defaultdict(lambda: None)
# Per-project lock to keep "check prior + set new" atomic.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def trigger_render_supersede(project_id: str, task_id: str, ir: ProjectIR) -> None:
    """Cancel any prior in-flight render for this project then run a new one.

    Designed to be awaited inside a FastAPI BackgroundTask. The
    cancellation is best-effort (renderer may have already started
    rendering and ignore the DELETE); the new render is fire-and-await.
    Task-store state for the *new* task is updated to running/completed/
    failed as usual.

    Concurrency model: prior task removal happens under the project's
    lock so two POST /render arriving in the same 100ms window don't
    both think they're the first. The actual render call runs OUTSIDE
    the lock so a long-running render doesn't serialize *future* edit
    requests on the same project.
    """
    async with _locks[project_id]:
        prior = _in_flight[project_id]
        _in_flight[project_id] = task_id

    if prior and prior != task_id:
        log.info("render_supersede", project_id=project_id, prior_task=prior, new_task=task_id)
        await cancel_render(prior)
        tasks_store.update_task(prior, status="superseded", stage="superseded")

    tasks_store.update_task(task_id, status="running", stage="render", progress=0.05)
    try:
        result = await render_project(ir, task_id=task_id)
        tasks_store.update_task(
            task_id, status="completed", progress=1.0, stage="done", result=result
        )
    except Exception as e:  # noqa: BLE001
        log.error("render_failed", task_id=task_id, error=str(e))
        tasks_store.update_task(task_id, status="failed", error=str(e))
    finally:
        async with _locks[project_id]:
            if _in_flight[project_id] == task_id:
                _in_flight[project_id] = None


def get_in_flight_render(project_id: str) -> str | None:
    """Return the in-flight render task_id for this project, if any.

    Intended for the Editor's "renders pending" indicator. Reads outside
    the lock — slightly stale but never wrong-shaped (the dict only
    holds str | None).
    """
    return _in_flight.get(project_id)


def reset_for_tests() -> None:
    """Test helper — wipe per-project state without re-importing."""
    _in_flight.clear()
    _locks.clear()


__all__ = ["trigger_render_supersede", "get_in_flight_render", "reset_for_tests"]
