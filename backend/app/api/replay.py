"""Replay API (Phase 2.5) — workbench event replay for the Visualize page.

The new Visualize page (``frontend/src/pages/Visualize.tsx``) loads a
task's full event history and lets the user scrub a timeline, watch the
three workbench panes repopulate, and export a 30-60s recording. The
backend's job is purely to serve:

- :func:`replay_events` — every persisted VisionEvent for a given task
  (mirror of ``GET /tasks/{id}/events/history`` but addressed by
  ``project`` / ``sample`` so the URL fits the page route);
- :func:`replay_tasks` — list of *all* tasks attached to a resource so
  the user can pick which prior run to revisit;
- :func:`replay_snapshot` — reconstruct ProjectIR / TemplateIR at a
  given sequence point by replaying lodash.set on the events. Used by
  the page's "时间线 50%" indicator + the recording export.

Symmetric endpoints under ``/samples/{id}/replay/*`` live in
``api/samples.py`` (added in the same Phase 2.5 patch) so extract task
replays follow the same shape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import tasks_store
from app.event_bus import get_event_bus
from app.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/replay/tasks")
def list_replay_tasks(project_id: str) -> dict:
    """Return all tasks attached to this project so the Visualize page
    can offer a picker. Newest first.
    """
    rows = tasks_store.list_by_resource("project", project_id)
    return {"project_id": project_id, "tasks": _shape_rows(rows)}


@router.get("/samples/{sample_id}/replay/tasks")
def list_replay_tasks_for_sample(sample_id: str) -> dict:
    """Same as the project variant, addressed by sample resource."""
    rows = tasks_store.list_by_resource("sample", sample_id)
    return {"sample_id": sample_id, "tasks": _shape_rows(rows)}


@router.get("/projects/{project_id}/replay/events")
def replay_events(project_id: str, task_id: str | None = None) -> dict:
    """Return every persisted VisionEvent for the given task.

    If ``task_id`` is omitted, defaults to the most recent task attached
    to this project — matches the PLAN 1696 spec.
    """
    target_task = _resolve_task("project", project_id, task_id)
    if target_task is None:
        raise HTTPException(404, f"no tasks attached to project {project_id}")
    return _events_payload(target_task)


@router.get("/samples/{sample_id}/replay/events")
def replay_events_for_sample(sample_id: str, task_id: str | None = None) -> dict:
    target_task = _resolve_task("sample", sample_id, task_id)
    if target_task is None:
        raise HTTPException(404, f"no tasks attached to sample {sample_id}")
    return _events_payload(target_task)


class _SnapshotBody(BaseModel):
    task_id: str
    sequence: int


@router.post("/projects/{project_id}/replay/snapshot")
def replay_snapshot(project_id: str, body: _SnapshotBody) -> dict:
    """Reconstruct the IR snapshot at a given sequence point.

    Reads all events for the task up to (and including) ``sequence``,
    replays their ``ir_target.path`` + ``ir_value`` writes into a fresh
    dict, and returns it. **Not persisted** — the Visualize page uses
    this purely for preview / MediaRecorder export (PLAN 1698).

    Note: the replay starts from an empty ``{}`` rather than the original
    IR. This is deliberate — the workbench's pre-Phase-2.5 design has
    always shown the IR pane as "fields filling in as events arrive",
    not "diff against initial state". The Visualize page recreates that
    same experience by accumulating from empty.
    """
    return _snapshot_payload(body.task_id, body.sequence)


@router.post("/samples/{sample_id}/replay/snapshot")
def replay_snapshot_for_sample(sample_id: str, body: _SnapshotBody) -> dict:
    return _snapshot_payload(body.task_id, body.sequence)


# ---------------------------------------------------------------------------
# Workbench event veto (PLAN 1700, S6 revision)
# ---------------------------------------------------------------------------


@router.post("/workbench/{task_id}/reject-event/{event_id}")
async def reject_event(task_id: str, event_id: str) -> dict:
    """Mark an AI decision as rejected by the human reviewer.

    Records the rejection as a fresh ``stage="2.5.veto"`` VisionEvent on
    the same task — does not rewrite the original event in events.jsonl
    (which would break the snapshot semantics). The frontend filters
    rejected event ids client-side; the persisted record lets future
    replays show "this decision was vetoed at T+Δ".

    PLAN 1700 originally proposed making veto a Patch; we keep it as a
    pure UI event so it composes with both extract-task and apply-task
    histories (where Patch semantics don't apply).
    """
    bus = get_event_bus()
    matches = [ev for ev in bus.replay(task_id) if ev.event_id == event_id]
    if not matches:
        raise HTTPException(404, f"event {event_id} not in task {task_id}")
    target = matches[0]
    from app.ir.vision_event import IRTarget, VisionEvent

    veto = VisionEvent(
        task_id=task_id,
        source="system",
        stage="2.5.veto",
        semantic_label=f"否决事件 #{event_id[:8]}",
        reasoning=(
            f"用户否决了原事件 stage={target.stage} sequence={target.sequence}。"
            "前端按 event_id 过滤；events.jsonl 保留原事件 + 本否决记录两条。"
        ),
        confidence=1.0,
        severity="warning",
        parent_event_id=event_id,
        ir_target=IRTarget(ir_type="ProjectIR", path=""),
        ir_value={"vetoed_event_id": event_id},
    )
    await bus.publish(task_id, veto)
    return {"ok": True, "vetoed_event_id": event_id, "veto_event_id": veto.event_id}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _shape_rows(rows: list[dict]) -> list[dict]:
    """Drop result_json blobs + flatten fields for the picker UI."""
    return [
        {
            "task_id": r["id"],
            "kind": r["kind"],
            "status": r["status"],
            "progress": r.get("progress", 0.0),
            "stage": r.get("stage"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "events_jsonl_path": r.get("events_jsonl_path"),
            "error": r.get("error"),
        }
        for r in rows
    ]


def _resolve_task(kind: str, rid: str, task_id: str | None) -> str | None:
    if task_id:
        # Confirm it belongs to this resource — otherwise replays for
        # other resources would be readable by URL spoofing.
        row = tasks_store.get_task(task_id)
        if not row:
            return None
        if row.get("resource_kind") != kind or row.get("resource_id") != rid:
            return None
        return task_id
    rows = tasks_store.list_by_resource(kind, rid)
    if not rows:
        return None
    return rows[0]["id"]  # newest first


def _events_payload(task_id: str) -> dict:
    bus = get_event_bus()
    events = bus.replay(task_id)
    row = tasks_store.get_task(task_id)
    return {
        "task_id": task_id,
        "task": {
            "kind": (row or {}).get("kind"),
            "status": (row or {}).get("status"),
            "stage": (row or {}).get("stage"),
            "resource_kind": (row or {}).get("resource_kind"),
            "resource_id": (row or {}).get("resource_id"),
        },
        "events": [e.model_dump(mode="json") for e in events],
    }


def _snapshot_payload(task_id: str, sequence: int) -> dict:
    bus = get_event_bus()
    events = bus.replay(task_id)
    snapshot: dict = {}
    for ev in events:
        if ev.sequence > sequence:
            break
        if ev.ir_target is None or not ev.ir_target.path:
            continue
        path = ev.ir_target.path
        op = ev.ir_target.op
        field = ev.ir_target.field
        full_path = f"{path}.{field}" if field else path
        _lodash_set(snapshot, full_path, ev.ir_value, op=op)
    return {
        "task_id": task_id,
        "sequence": sequence,
        "snapshot": snapshot,
        "events_count": len(events),
    }


def _lodash_set(obj: dict, path: str, value, *, op: str = "set") -> None:
    """Minimal lodash.set on a nested dict / list structure.

    Supports dotted paths with integer segments interpreted as list
    indices. The ``op`` aligns with ``IRTarget.op``:
    - ``set``: overwrite the leaf.
    - ``append``: leaf is expected to be a list — append.
    - ``remove``: drop the leaf if it exists.

    Mirrors the lodash.set the frontend uses in ``state/workbench.ts`` so
    the reconstructed snapshot here matches what the live workbench
    displays.
    """
    if not path:
        return
    segs = [_int_or_str(s) for s in path.split(".")]
    cur = obj
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if last:
            if op == "remove":
                if isinstance(cur, dict):
                    cur.pop(seg, None)
                elif isinstance(cur, list) and isinstance(seg, int) and 0 <= seg < len(cur):
                    cur.pop(seg)
                return
            if op == "append":
                existing = cur.get(seg) if isinstance(cur, dict) else None
                if not isinstance(existing, list):
                    existing = []
                existing.append(value)
                if isinstance(cur, dict):
                    cur[seg] = existing
                return
            if isinstance(cur, dict):
                cur[seg] = value
            elif isinstance(cur, list) and isinstance(seg, int):
                while len(cur) <= seg:
                    cur.append(None)
                cur[seg] = value
            return
        nxt_seg = segs[i + 1]
        default = [] if isinstance(nxt_seg, int) else {}
        if isinstance(cur, dict):
            if seg not in cur or not isinstance(cur[seg], (dict, list)):
                cur[seg] = default
            cur = cur[seg]
        elif isinstance(cur, list) and isinstance(seg, int):
            while len(cur) <= seg:
                cur.append(default if not cur else (type(cur[0])() if cur[0] else default))
            if not isinstance(cur[seg], (dict, list)):
                cur[seg] = default
            cur = cur[seg]
        else:
            return


def _int_or_str(s: str):
    try:
        return int(s)
    except ValueError:
        return s
