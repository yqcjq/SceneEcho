"""One-shot migration: hoist ``Slot.style.caption`` (CaptionStyle | None)
inline payloads into model-level ``TemplateIR.caption_style_palette`` +
``Slot.style.caption_palette_idx``.

decisions/010 reshapes TemplateIR — captions live in a per-template palette
referenced by index instead of being inlined on every Slot. Existing rows
written before P1 carry the legacy shape (Slot.style.caption directly
holds CaptionStyle). This script reads each row, deduplicates the inline
captions per the same signature key skeleton.py uses (font / size / color /
stroke / layout / semantic_purpose), writes the dedup'd list to the new
palette field, and replaces each Slot's caption with the palette index.

Idempotent: rows already in the new shape (caption_style_palette non-empty
OR caption is None across every Slot) skip cleanly. Run with
``BACKEND_DATA_ROOT`` env pointing at the data dir, or ``--dry-run`` to
just print what would change. Run from repo root::

    python backend/scripts/migrate_caption_palette.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Imports must come after the sys.path tweak so ``app.*`` resolves.
from app.ir.template import CaptionStyle, TemplateIR  # noqa: E402


def _palette_key(style: dict) -> tuple:
    """Match skeleton.py::_palette_key — coarse caption signature.

    Operates on ``model_dump()`` dicts (not pydantic instances) because the
    migration walks raw JSON loaded from sqlite, before constructing
    TemplateIR. Casting to int / str defensively in case the legacy row
    drifted from the canonical types.
    """
    return (
        str(style.get("font_family", "")),
        int(style.get("size", 0) or 0),
        str(style.get("color", "")),
        str(style.get("stroke_color") or ""),
        int(style.get("stroke_width", 0) or 0),
        str(style.get("layout", "")),
        int(style.get("max_chars_per_line", 0) or 0),
        str(style.get("semantic_purpose", "")),
    )


def _migrate_ir_dict(ir_dict: dict) -> tuple[dict, bool]:
    """Return (new_ir_dict, changed). Idempotent.

    A row is considered already-migrated when ``caption_style_palette`` is
    a list (even empty) AND no Slot.style.caption holds a non-null inline
    CaptionStyle. We still ensure the field exists on the dict for new
    pydantic compatibility but mark ``changed=False`` so the caller can
    skip the SQL UPDATE.
    """
    skeleton = ir_dict.get("skeleton") or []
    palette: list[dict] = list(ir_dict.get("caption_style_palette") or [])
    key_to_idx: dict[tuple, int] = {
        _palette_key(p): i for i, p in enumerate(palette)
    }

    needs_write = False
    for slot in skeleton:
        style_block = slot.get("style") or {}
        legacy_caption = style_block.get("caption")
        if legacy_caption is None:
            # New schema: ensure caption_palette_idx exists (None default).
            style_block.setdefault("caption_palette_idx", None)
            slot["style"] = style_block
            continue
        # Legacy inline payload — extract into palette.
        needs_write = True
        canonical = CaptionStyle(**legacy_caption).model_dump(mode="json")
        key = _palette_key(canonical)
        if key not in key_to_idx:
            key_to_idx[key] = len(palette)
            palette.append(canonical)
        idx = key_to_idx[key]
        # Drop the inline caption + write idx in its place. Keep the rest
        # of style untouched (visual / stickers / transition_in/out).
        style_block.pop("caption", None)
        style_block["caption_palette_idx"] = idx
        slot["style"] = style_block

    ir_dict["skeleton"] = skeleton
    ir_dict["caption_style_palette"] = palette
    # Re-validate end-state through the pydantic model so we never write a
    # row that the new IR can't parse. ``model_dump(mode="json")`` then
    # serializes back the canonical shape (default fields filled, etc).
    canonical_ir = TemplateIR.model_validate(ir_dict).model_dump(mode="json")
    return canonical_ir, needs_write


def _data_root() -> Path:
    env = os.environ.get("BACKEND_DATA_ROOT")
    if env:
        return Path(env)
    return REPO_ROOT / "backend" / "data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which rows need migration without writing.",
    )
    args = parser.parse_args()

    db_path = _data_root() / "kb.sqlite"
    if not db_path.exists():
        print(f"no kb.sqlite at {db_path} — nothing to migrate")
        return 0

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT id, ir_json FROM templates").fetchall()
    except sqlite3.OperationalError as e:
        print(f"templates table missing — {e}; nothing to migrate")
        return 0

    migrated = 0
    skipped = 0
    failed = 0
    for row in rows:
        tid = row["id"]
        try:
            ir_dict = json.loads(row["ir_json"])
        except json.JSONDecodeError as e:
            print(f"[skip] {tid}: bad JSON ({e})")
            failed += 1
            continue
        try:
            new_ir, changed = _migrate_ir_dict(ir_dict)
        except Exception as e:  # noqa: BLE001
            print(f"[fail] {tid}: {type(e).__name__}: {e}")
            failed += 1
            continue
        if not changed:
            skipped += 1
            continue
        if args.dry_run:
            palette_size = len(new_ir.get("caption_style_palette") or [])
            print(f"[would migrate] {tid}: palette size {palette_size}")
            migrated += 1
            continue
        con.execute(
            "UPDATE templates SET ir_json = ? WHERE id = ?",
            (json.dumps(new_ir, ensure_ascii=False), tid),
        )
        migrated += 1
        print(f"[migrated] {tid}")
    if not args.dry_run:
        con.commit()
    con.close()
    print(
        f"\nmigrated={migrated}  skipped(already-new)={skipped}  failed={failed}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
