"""Prompt asset loader.

Each subcapability ships a markdown file alongside this package; loaders
read them by stage name. Markdown is fine because we never ship them to a
chat-completion endpoint as messages directly — we use the body as the
system prompt with optional substitutions.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """Read ``backend/app/llm/prompts/{name}.md`` once per process."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt asset missing: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **substitutions: object) -> str:
    """Load + ``str.format``-substitute simple ``{key}`` placeholders.

    Markdown headers / fenced code blocks are passed through verbatim.
    """
    body = load_prompt(name)
    if not substitutions:
        return body
    return body.format(**substitutions)
