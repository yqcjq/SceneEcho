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
    # Phase 2: per-field degradation flags, same shape as TemplateIR.degraded.
    # Keys are dotted ProjectIR paths (e.g. "captions" / "sections.0.segments"
    # / "bgm_track" / "ledger"). The apply pipeline wraps every step with
    # ``_safe(label, ir_path, coro)``; failures land here so the workbench
    # banner + Editor right-pane can flag partial results without losing the
    # rest of the project. Unlike TemplateIR.degraded, this is per-project
    # state, persisted with the rest of ProjectIR into projects/{id}/project.json.
    degraded: dict[str, str] = Field(default_factory=dict)
