"""Task state store. SQLite-backed; Phase 0 minimal schema."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    stage TEXT DEFAULT '',
    result_json TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


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


def create_task(kind: str, task_id: str | None = None) -> str:
    tid = task_id or uuid.uuid4().hex
    now = time.time()
    with _conn() as con:
        con.execute(
            "INSERT INTO tasks (id, kind, status, progress, stage, created_at, updated_at)"
            " VALUES (?, ?, 'pending', 0, '', ?, ?)",
            (tid, kind, now, now),
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
