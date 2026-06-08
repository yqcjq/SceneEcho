"""CI gate: every VisionEvent ``stage="..."`` literal matches the canonical
prefix table from PLAN.md ("AI 调用协议 · stage 命名规范").

Run as: ``python scripts/check_stage_naming.py``. Exit 0 = clean.

Implementation note: a naive grep flagged unrelated callsites
(``tasks_store.update_task(stage="render")``, test scaffolding) because
the keyword name happens to be reused for non-event labels. The check is
therefore AST-aware: only stages passed to VisionEvent / chat_vision /
chat_text / chat_vision_dual / classify_caption_function or assigned to a
module-level ``STAGE = "..."`` constant are inspected. Everything else
ignores the ``stage`` keyword.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Allowed prefixes — keep aligned with PLAN.md "stage 命名规范" table.
ALLOWED_PREFIXES: tuple[str, ...] = (
    "0.5.mock",
    "1A.",
    "1B.",
    "2.",
    "2.5.",
    "2.6.",
    "3.step",
    "4.",
    "5.aigc.",
)

# AST: callees whose ``stage=`` argument is a VisionEvent stage. Adding the
# raw class name and the chat methods covers everything we ship without
# over-flagging task-progress labels.
EVENT_CALL_NAMES = {
    "VisionEvent",
    "chat_vision",
    "chat_text",
    "chat_vision_dual",
    "classify_caption_function",
}

EXEMPT_DIRS = (
    "scripts/",
    "tests/",
    "backend/tests/",
    "backend/app/llm/prompts/scenarios/",
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


def _is_allowed(stage: str) -> bool:
    return any(stage.startswith(p) for p in ALLOWED_PREFIXES)


def _gather_violations(tree: ast.AST, path: Path) -> list[tuple[Path, int, str]]:
    """Walk the tree, flag VisionEvent-context stage literals that don't match."""
    out: list[tuple[Path, int, str]] = []

    class V(ast.NodeVisitor):
        def visit_Call(self, n: ast.Call) -> None:  # noqa: N802
            callee = _callee_name(n.func)
            if callee in EVENT_CALL_NAMES:
                for kw in n.keywords or ():
                    if kw.arg == "stage" and isinstance(kw.value, ast.Constant):
                        v = kw.value.value
                        if isinstance(v, str) and not _is_allowed(v):
                            out.append((path, n.lineno, v))
            self.generic_visit(n)

        def visit_Assign(self, n: ast.Assign) -> None:  # noqa: N802
            # Module-level ``STAGE = "..."`` constants.
            if (
                len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id.upper().startswith("STAGE")
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)
                and not _is_allowed(n.value.value)
            ):
                out.append((path, n.lineno, n.value.value))
            self.generic_visit(n)

    V().visit(tree)
    return out


def _callee_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def main() -> int:
    violations: list[tuple[Path, int, str]] = []
    for py in REPO_ROOT.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(d) for d in EXEMPT_DIRS) or _is_in_venv(rel):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        violations.extend(_gather_violations(tree, py))
    if not violations:
        print("stage naming: OK")
        return 0
    print("stage naming violations (PLAN.md 'AI 调用协议 · stage 命名规范'):", file=sys.stderr)
    for path, line_no, stage in violations:
        rel = path.relative_to(REPO_ROOT).as_posix()
        print(f"  {rel}:{line_no} stage={stage!r}", file=sys.stderr)
    print(
        f"\n{len(violations)} violation(s). Allowed prefixes: {', '.join(ALLOWED_PREFIXES)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
