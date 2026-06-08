"""Smoke test: build a minimal ProjectIR + round-trip through model_dump_json."""

from __future__ import annotations

from app.ir.project import Caption, PlacedSegment, ProjectIR, Section
from app.ir.template import CaptionStyle, StyleRule


def test_min_project_ir_roundtrip():
    ir = ProjectIR(
        project_id="p1",
        user_material="samples/x/normalized.mp4",
        sections=[
            Section(
                topic="demo",
                segments=[
                    PlacedSegment(
                        slot_role="主体",
                        src_timerange=(0.0, 5.0),
                        timeline_start=0.0,
                        applied_style=StyleRule(),
                    )
                ],
            )
        ],
        captions=[Caption(text="Hello", start=0.0, end=2.0, style=CaptionStyle())],
    )
    raw = ir.model_dump_json()
    ir2 = ProjectIR.model_validate_json(raw)
    assert ir2.captions[0].text == "Hello"
    assert ir2.sections[0].segments[0].src_timerange == (0.0, 5.0)
