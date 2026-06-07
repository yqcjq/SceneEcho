"""Thin wrapper: pydantic models -> shared/ir.schema.json.

Run from repo root: `python scripts/gen_schema.py`.
CI also runs this before `pnpm -r gen:types` and asserts the working tree is clean.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ir.export import export_json_schema  # noqa: E402


def main() -> None:
    out = export_json_schema(REPO_ROOT / "shared" / "ir.schema.json")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
