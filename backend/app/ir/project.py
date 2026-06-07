"""ProjectIR — instantiated timeline (EDL + captions). Rendered to MP4."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.ir.template import CaptionStyle, StyleRule


class PlacedSegment(BaseModel):
    slot_role: str
    source_unit_ids: list[int] = Field(default_factory=list)
    src_timerange: tuple[float, float]
    timeline_start: float
    speed: float = 1.0
    applied_style: StyleRule = Field(default_factory=StyleRule)
    is_fill: bool = False
    use_aigc_broll: bool = False
    aigc_broll_path: str | None = None


class Caption(BaseModel):
    text: str
    start: float
    end: float
    style: CaptionStyle = Field(default_factory=CaptionStyle)


class Gap(BaseModel):
    slot_role: str
    reason: str
    fill_strategy: str
    fill_result: str = ""


class Section(BaseModel):
    topic: str = ""
    template_id: str = ""
    segments: list[PlacedSegment] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)


class ProjectIR(BaseModel):
    project_id: str
    user_material: str
    sections: list[Section] = Field(default_factory=list)
    captions: list[Caption] = Field(default_factory=list)
    canvas: dict = Field(default_factory=lambda: {"width": 1080, "height": 1920, "fps": 30})
    allow_aigc_broll: bool = False
    bgm_track: str | None = None
    version: int = 1
