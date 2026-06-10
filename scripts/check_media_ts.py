"""CI gate: entity-style VisionEvent constructions carry media_ts (Phase 2.6).

Phase 2.6 introduces ``VisionEvent.media_ts`` / ``media_ts_range`` so the
media-timeline view can anchor each AI decision to its source-video moment.
The convention: any event that pins a ``frame_url`` is *anchored* to that
frame and should expose ``media_ts`` (or ``media_ts_range`` for span events).
System / progress events without ``frame_url`` are exempt — they speak about
the run, not the video.

This script walks every ``VisionEvent(...)`` constructor call across the
backend, and for each call that passes ``frame_url=``, asserts at least
one of ``media_ts=`` / ``media_ts_range=`` is also present. The check is
syntactic (kwargs look-up); it doesn't try to evaluate values, so a
``frame_url=None`` literal still counts as "anchored" — that's a code smell
worth fixing in the call site, not papering over here.

Run as: ``python scripts/check_media_ts.py``. Exit 0 = clean.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXEMPT_FILES = (
    "tests/",
    "scripts/",
    "node_modules/",
    "dist/",
    "data/",
)


def _is_in_venv(rel: str) -> bool:
    return (
        ".venv/" in rel
        or rel.startswith("venv/")
        or "/venv/" in rel
        or "site-packages/" in rel
    )


def _is_exempt(rel: str) -> bool:
    return any(seg in rel for seg in EXEMPT_FILES)


def _kwargs(call: ast.Call) -> set[str]:
    return {kw.arg for kw in call.keywords if kw.arg}


def _is_vision_event_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name) and f.id == "VisionEvent":
        return True
    if isinstance(f, ast.Attribute) and f.attr == "VisionEvent":
        return True
    return False


def main() -> int:
    violations: list[tuple[Path, int]] = []
    for py in REPO_ROOT.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if _is_exempt(rel) or _is_in_venv(rel):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_vision_event_call(node):
                continue
            kw = _kwargs(node)
            if "frame_url" not in kw:
                continue
            if "media_ts" in kw or "media_ts_range" in kw:
                continue
            violations.append((py, node.lineno))
    if not violations:
        print("media_ts: OK")
        return 0
    print("media_ts violations (Phase 2.6 dual-axis):", file=sys.stderr)
    for path, lineno in violations:
        rel = path.relative_to(REPO_ROOT).as_posix()
        print(
            f"  {rel}:{lineno} VisionEvent(...) sets frame_url= but no "
            "media_ts= / media_ts_range=",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
