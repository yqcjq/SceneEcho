"""1B · Template KB store (SQLite).

Lives in the same ``data/kb.sqlite`` as ``tasks`` (already WAL-enabled by
``tasks_store._conn``). One row per template; the source events JSONL is
*not* duplicated here — the row carries ``last_extract_task_id`` and the
JSONL path is rediscovered through ``tasks.events_jsonl_path``. This is
PLAN.md's path-scheme B in action: events live with the resource, the KB
row only points back.

Schema (additive — never alter without a docs decision):
    id                    TEXT PRIMARY KEY  # tpl_<sample_id>_<ts> or user-supplied
    name                  TEXT NOT NULL
    source_sample         TEXT NOT NULL
    ir_json               TEXT NOT NULL     # serialized TemplateIR
    tags_json             TEXT NOT NULL     # convenience for listings
    thumbnail_path        TEXT              # samples/<sid>/thumbnail.jpg
    last_extract_task_id  TEXT              # for event replay
    created_at            REAL NOT NULL
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings
from app.ir.template import Tags, TemplateIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_sample TEXT NOT NULL,
    ir_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    thumbnail_path TEXT,
    last_extract_task_id TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_sample ON templates(source_sample);
"""


def _db_path() -> Path:
    return get_settings().data_root / "kb.sqlite"


@contextmanager
def _conn():
    """Mirror tasks_store._conn — share the same SQLite file in WAL."""
    import sqlite3

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


def save_template(
    ir: TemplateIR,
    *,
    thumbnail_path: str | None = None,
    last_extract_task_id: str | None = None,
) -> str:
    """Insert (or replace) a template row. Returns the template id.

    Replace-on-conflict is correct here: re-running extract on the same
    sample with the same target id should overwrite, not duplicate. The
    Phase 1A events JSONL is not touched — only the IR snapshot.

    ``init_db`` is **not** called here: ``main.py``'s lifespan owns the
    schema bootstrap (see ARCHITECTURE D24). Callers in tests must use
    a temp DATA_ROOT + ``init_db()`` explicitly via the conftest fixture.
    """
    payload = (
        ir.id,
        ir.name,
        ir.source_sample,
        ir.model_dump_json(),
        ir.tags.model_dump_json(),
        thumbnail_path,
        last_extract_task_id,
        time.time(),
    )
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO templates "
            "(id, name, source_sample, ir_json, tags_json, thumbnail_path,"
            " last_extract_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            payload,
        )
    return ir.id


def get_template(template_id: str) -> dict | None:
    """Return the template row + parsed TemplateIR (or None)."""
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["ir"] = TemplateIR.model_validate_json(d.pop("ir_json")).model_dump(mode="json")
    except Exception:  # noqa: BLE001
        d["ir"] = None
    try:
        d["tags"] = json.loads(d.pop("tags_json"))
    except Exception:  # noqa: BLE001
        d["tags"] = Tags().model_dump()
    return d


def list_templates() -> list[dict]:
    """Return all templates, newest first. Heavy fields omitted from list view."""
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, name, source_sample, tags_json, thumbnail_path,"
            " last_extract_task_id, created_at FROM templates ORDER BY created_at DESC"
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["tags"] = json.loads(d.pop("tags_json"))
        except Exception:  # noqa: BLE001
            d["tags"] = Tags().model_dump()
        out.append(d)
    return out


def delete_template(template_id: str) -> bool:
    init_db()
    with _conn() as con:
        cur = con.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0


def update_template_tags(template_id: str, tags: Tags) -> bool:
    """Patch the tags column (UI-driven edits) + sync into ir_json."""
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT ir_json FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
        if not row:
            return False
        try:
            ir = TemplateIR.model_validate_json(row["ir_json"])
        except Exception:  # noqa: BLE001
            return False
        ir.tags = tags
        con.execute(
            "UPDATE templates SET tags_json = ?, ir_json = ? WHERE id = ?",
            (tags.model_dump_json(), ir.model_dump_json(), template_id),
        )
    return True


def update_caption_placeholder(
    template_id: str, slot_idx: int, placeholder_text: list[str]
) -> bool:
    """Manually override a slot caption's placeholder_text (PLAN 1538).

    decisions/010 落地后字幕样式存放在模板级 ``caption_style_palette``，
    Slot 通过 ``style.caption_palette_idx`` 引用。本函数解引用 idx 取出对应
    palette 元素后更新其 ``placeholder_text``——所有引用同一 palette idx 的
    Slot 一起获益。renderer 的 template_preview 模式与 Phase 2 caption-fill
    LLM 都从 palette 元素读这个字段。
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT ir_json FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
        if not row:
            return False
        try:
            ir = TemplateIR.model_validate_json(row["ir_json"])
        except Exception:  # noqa: BLE001
            return False
        if slot_idx < 0 or slot_idx >= len(ir.skeleton):
            return False
        slot = ir.skeleton[slot_idx]
        idx = slot.style.caption_palette_idx
        if idx is None or not (0 <= idx < len(ir.caption_style_palette)):
            return False
        ir.caption_style_palette[idx] = ir.caption_style_palette[idx].model_copy(
            update={"placeholder_text": list(placeholder_text)}
        )
        con.execute(
            "UPDATE templates SET ir_json = ? WHERE id = ?",
            (ir.model_dump_json(), template_id),
        )
    return True


__all__ = [
    "delete_template",
    "get_template",
    "init_db",
    "list_templates",
    "save_template",
    "update_caption_placeholder",
    "update_template_tags",
]
