"""CI gate: two-stage VLM calls must thread ``parent_event_id`` (Phase 2.6 prep).

A function whose name suggests it is the "phase 2" of a chained
detection — names ending in ``_refine``, ``_phase2``, or ``_classify`` —
must call ``chat_vision`` (directly or via wrappers) with a
``parent_event_id=`` keyword arg. The Phase 2.6 gantt-view uses this to
draw the dashed causal-chain edges between events.

Run as: ``python scripts/check_parent_event_id.py``. Exit 0 = clean.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Functions whose names imply they're a phase-2 step that must keep the
# parent's event id alive.
PHASE2_NAME_SUFFIXES = ("_refine", "_phase2", "_classify")

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


def _calls_with_parent(node: ast.AST) -> bool:
    """True iff the function body contains any call passing ``parent_event_id=``."""

    class V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_Call(self, c: ast.Call) -> None:  # noqa: N802
            for kw in c.keywords or ():
                if kw.arg == "parent_event_id":
                    self.found = True
                    break
            self.generic_visit(c)

    v = V()
    v.visit(node)
    return v.found


def _is_phase2(name: str) -> bool:
    return any(name.endswith(suffix) for suffix in PHASE2_NAME_SUFFIXES)


def main() -> int:
    violations: list[tuple[Path, int, str]] = []
    for py in REPO_ROOT.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(d) for d in EXEMPT_FILES) or _is_in_venv(rel):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not _is_phase2(node.name):
                    continue
                if not _calls_with_parent(node):
                    violations.append((py, node.lineno, node.name))
    if not violations:
        print("parent_event_id: OK")
        return 0
    print("parent_event_id violations (Phase 2.6 gantt prep):", file=sys.stderr)
    for path, lineno, name in violations:
        rel = path.relative_to(REPO_ROOT).as_posix()
        print(
            f"  {rel}:{lineno} `{name}` body missing `parent_event_id=` kwarg on its calls",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
