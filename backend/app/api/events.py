"""SSE event stream + history endpoints for the AI workbench (D13).

The stream protocol takes advantage of ``EventBus.subscribe_with_snapshot``:
events with sequence ≤ snapshot are persisted in the JSONL (replayed once);
events with sequence > snapshot will arrive on the live queue. The two sets
do not overlap, so no client-side dedup is required — the previous
sequence-based filter has been removed along with the race condition that
forced it to exist.

This module is intentionally narrow: the gantt + media-timeline aggregations
that Phase 2.6 needs are derived **client-side** from the same event stream
that the SSE endpoint already pushes. Aggregating server-side would have
duplicated work the client already did (the workbench store accumulates
every event for the IR snapshot), and would have forced the gantt page to
re-fetch on every SSE arrival to stay live. The single source of truth is
the event JSONL itself, exposed once via SSE and once via the history
endpoint; views derive shape from those events without a parallel HTTP
projection.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app import tasks_store
from app.event_bus import get_event_bus
from app.ir.vision_event import VisionEvent

router = APIRouter()


def _format(event: VisionEvent) -> dict[str, str]:
    """Render a VisionEvent for ``EventSourceResponse``.

    The ``id`` field is mandatory: browsers replay it via ``Last-Event-ID``
    on reconnect, which is what makes resume possible.
    """
    return {
        "id": event.event_id,
        "event": "vision",
        "data": event.model_dump_json(),
    }


def _terminal_done(t: dict | None) -> dict[str, str] | None:
    """If task is in a terminal state, return the SSE ``done`` payload."""
    if t and t.get("status") in ("completed", "failed"):
        return {"event": "done", "data": json.dumps({"status": t["status"]})}
    return None


async def _stream(task_id: str, last_event_id: str | None, request: Request) -> AsyncIterator[dict]:
    bus = get_event_bus()
    queue, snapshot = await bus.subscribe_with_snapshot(task_id)
    try:
        # Replay history bounded by the snapshot. After this point every
        # event we yield from the queue has sequence > snapshot — no overlap,
        # no dedup.
        for ev in bus.replay(task_id, from_event_id=last_event_id, until_seq=snapshot):
            if await request.is_disconnected():
                return
            yield _format(ev)

        # If the task already finished before we subscribed (close_task may
        # have run before our subscribe got a chance to receive a sentinel)
        # we'd otherwise sit in wait_for forever.
        done = _terminal_done(tasks_store.get_task(task_id))
        if done:
            yield done
            return

        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                # No live events for 15s — re-check task status so a
                # completed-with-no-future-events task can still close.
                done = _terminal_done(tasks_store.get_task(task_id))
                if done:
                    yield done
                    return
                continue
            if event is None:
                # close_task() sentinel → tell the browser to stop reconnecting.
                yield {"event": "done", "data": "{}"}
                return
            yield _format(event)
            done = _terminal_done(tasks_store.get_task(task_id))
            if done:
                yield done
                return
    finally:
        bus.unsubscribe(task_id, queue)


@router.get("/tasks/{task_id}/events")
async def stream_events(
    task_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    """SSE endpoint — vision events + heartbeats. ``Last-Event-ID`` resumes."""
    return EventSourceResponse(
        _stream(task_id, last_event_id, request),
        ping=15,  # heartbeat comment every 15s
    )


@router.get("/tasks/{task_id}/events/history")
def history(task_id: str) -> JSONResponse:
    """One-shot replay of every persisted event for a task (no live stream).

    The Visualize replay page consumes this; the live SSE endpoint already
    replays history on connect. Phase 2.6 gantt + media-timeline views also
    consume the same events through the workbench store (which is
    populated by SSE), so they don't need a separate aggregate endpoint.
    """
    bus = get_event_bus()
    events = bus.replay(task_id)
    return JSONResponse([e.model_dump(mode="json") for e in events])
