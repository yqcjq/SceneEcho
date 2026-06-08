"""Task state store. SQLite-backed; Phase 0.5 schema.

The Phase 0.5 second-pass dropped ``last_event_sequence`` — the JSONL tail
is now the sole source of truth for the high-water mark (see
``app.event_bus.EventBus._read_jsonl_tail_seq``). Existing databases that
were migrated through the earlier transitional schema keep the orphan
column; SQLite tolerates the unread column and there's no need for a
destructive DROP COLUMN migration.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import get_settings

# Initial schema. Existing databases get any missing columns via the
# idempotent migration in init_db() below.
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    stage TEXT DEFAULT '',
    resource_kind TEXT,
    resource_id TEXT,
    events_jsonl_path TEXT,
    result_json TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

_PHASE_0_5_COLUMNS: tuple[tuple[str, str], ...] = (
    ("resource_kind", "ALTER TABLE tasks ADD COLUMN resource_kind TEXT"),
    ("resource_id", "ALTER TABLE tasks ADD COLUMN resource_id TEXT"),
    ("events_jsonl_path", "ALTER TABLE tasks ADD COLUMN events_jsonl_path TEXT"),
)


def _db_path() -> Path:
    return get_settings().data_root / "kb.sqlite"


@contextmanager
def _conn():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(SCHEMA)
        existing = {row["name"] for row in con.execute("PRAGMA table_info(tasks)").fetchall()}
        for col, ddl in _PHASE_0_5_COLUMNS:
            if col not in existing:
                con.execute(ddl)


def create_task(
    kind: str,
    *,
    resource_kind: str | None = None,
    resource_id: str | None = None,
    task_id: str | None = None,
) -> str:
    tid = task_id or uuid.uuid4().hex
    now = time.time()
    events_jsonl_path: str | None = None
    if resource_kind and resource_id:
        # Local import keeps event_bus → tasks_store the only direction we
        # tolerate (tasks_store consumes a static helper from event_bus, no
        # runtime side-effect).
        from app.event_bus import EventBus

        events_jsonl_path = EventBus.resolve_events_path(resource_kind, resource_id, tid)
    with _conn() as con:
        con.execute(
            "INSERT INTO tasks (id, kind, status, progress, stage, resource_kind,"
            " resource_id, events_jsonl_path, created_at, updated_at)"
            " VALUES (?, ?, 'pending', 0, '', ?, ?, ?, ?, ?)",
            (tid, kind, resource_kind, resource_id, events_jsonl_path, now, now),
        )
    return tid


def update_task(
    task_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    stage: str | None = None,
    result: Any | None = None,
    error: str | None = None,
) -> None:
    sets: list[str] = []
    args: list[Any] = []
    if status is not None:
        sets.append("status = ?")
        args.append(status)
    if progress is not None:
        sets.append("progress = ?")
        args.append(progress)
    if stage is not None:
        sets.append("stage = ?")
        args.append(stage)
    if result is not None:
        sets.append("result_json = ?")
        args.append(json.dumps(result, ensure_ascii=False))
    if error is not None:
        sets.append("error = ?")
        args.append(error)
    if not sets:
        return
    sets.append("updated_at = ?")
    args.append(time.time())
    args.append(task_id)
    with _conn() as con:
        con.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", args)


def get_task(task_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("result_json"):
            try:
                d["result"] = json.loads(d.pop("result_json"))
            except Exception:  # noqa: BLE001
                d["result"] = None
        else:
            d.pop("result_json", None)
            d["result"] = None
        return d
