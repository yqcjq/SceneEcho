"""AIGC v0 placeholder — Phase 1B scaffolding for Phase 5 fill-in.

PLAN.md explicitly defers AIGC generation (sticker images, B-roll video,
covers) to Phase 5 with user opt-in. Phase 1B just keeps the module path
reserved so api/templates.py / future agent endpoints can ``import``
without breaking when Phase 5 lands.
"""

from __future__ import annotations


async def generate_sticker_image(description: str) -> str | None:  # pragma: no cover
    """Phase 5 will implement; Phase 1B returns None to mean "skip"."""
    return None


async def generate_broll(prompt: str) -> str | None:  # pragma: no cover
    return None


__all__ = ["generate_broll", "generate_sticker_image"]
