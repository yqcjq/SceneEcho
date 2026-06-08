"""Verify IR JSON Schema export produces a valid document with expected top-level defs."""

from __future__ import annotations

import json

from app.ir.export import build_schema, export_json_schema


def test_build_schema_has_top_level_defs():
    schema = build_schema()
    assert "$defs" in schema
    defs = schema["$defs"]
    for name in (
        "ProjectIR",
        "TemplateIR",
        "TranscriptLedger",
        "Patch",
        "Caption",
        "PlacedSegment",
    ):
        assert name in defs, f"missing {name} in IR schema"


def test_export_writes_file(tmp_path):
    out = export_json_schema(tmp_path / "ir.schema.json")
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["title"] == "SceneEcho IR"
