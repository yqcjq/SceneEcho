"""CI gate: every AI client method emits at least one VisionEvent (D13).

Walks the LLM client + audio / extract / understand modules looking for
async function definitions whose names match the AI-call pattern, and
asserts the body calls ``event_bus.publish`` (or returns from a
:class:`_RealClientBase` method that does so internally).

Run as: ``python scripts/check_event_emission.py``. Exit 0 = clean.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Functions whose body must contain ``event_bus.publish(...)`` (or be a
# decorator-renamed call into one). Names match the canonical "I'm an AI
# client method" naming we use across extract / understand / agent layers.
TRACKED_NAME_PATTERNS = (
    "chat_vision",
    "chat_text",
    "chat_vision_dual",
    "transcribe",
    "extract_bgm",
    "detect_scenes",
    "detect_captions",
    "detect_stickers",
    "detect_masks",
    "judge_zoom_direction",
    "estimate_zoom_curve",
    "verify_caption_anim",
    "classify_transitions",
    "classify_color_lut",
    "classify_caption_function",
)

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


def _walks_through_publish(node: ast.AST) -> bool:
    """Return True if the AST contains a call shaped like ``event_bus.publish(...)``.

    Accepts both ``await event_bus.publish(...)`` and method form
    ``self._bus.publish(...)`` — anything ending in ``.publish``.
    Also accepts a call to ``chat_vision`` / ``chat_text`` / ``_invoke``
    because those internally publish (so wrappers that delegate are fine).
    """

    class V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_Call(self, n: ast.Call) -> None:  # noqa: N802
            f = n.func
            if isinstance(f, ast.Attribute):
                if f.attr in (
                    "publish",
                    "publish_many",
                    "chat_vision",
                    "chat_text",
                    "chat_vision_dual",
                    "_invoke",
                ):
                    self.found = True
            elif isinstance(f, ast.Name) and f.id in {"chat_vision_dual"}:
                self.found = True
            self.generic_visit(n)

    v = V()
    v.visit(node)
    return v.found


def _is_tracked(name: str) -> bool:
    return any(p in name for p in TRACKED_NAME_PATTERNS)


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
                if not _is_tracked(node.name):
                    continue
                # Skip abstract methods — they have no body.
                if any(
                    isinstance(d, ast.Name) and d.id == "abstractmethod"
                    for d in node.decorator_list
                ):
                    continue
                if not _walks_through_publish(node):
                    violations.append((py, node.lineno, node.name))
    if not violations:
        print("event emission: OK")
        return 0
    print("event emission violations (D13):", file=sys.stderr)
    for path, lineno, name in violations:
        rel = path.relative_to(REPO_ROOT).as_posix()
        print(f"  {rel}:{lineno} `{name}` body missing event_bus.publish", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
