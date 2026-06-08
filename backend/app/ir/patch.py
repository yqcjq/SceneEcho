"""Patch — unified edit op for NL / panel / review / timeline sources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PatchOp = Literal[
    "set_caption_style",
    "set_visual_style",
    "adjust_rhythm",
    "set_emphasis",
    "swap_template",
    "delete_segment",
    "set_canvas",
    "set_bgm",
    "mark_aigc",
    "manual_drop",
    "restore_vad_segment",
    "keep_dup",
    "merge_sections",
    "split_section",
    "rename_section",
    "override_unit_text",
    "reorder_sections",
]


class Patch(BaseModel):
    op: PatchOp
    target: dict = Field(default_factory=dict)
    value: dict = Field(default_factory=dict)
    source: str = "nl"  # nl | panel | review | timeline
    timestamp: str = ""
    pipeline_step: int | None = None
