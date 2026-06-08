"""Export all top-level IR pydantic models as a single JSON Schema document.

Consumed by renderer/frontend codegen scripts (json-schema-to-zod).
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from app.ir.ledger import TranscriptLedger, Unit
from app.ir.patch import Patch
from app.ir.project import Caption, Gap, PlacedSegment, ProjectIR, Section
from app.ir.template import (
    AudioStyle,
    CaptionStyle,
    Slot,
    StickerEvent,
    StyleRule,
    Tags,
    TemplateIR,
    VisualStyle,
    ZoomKeyframe,
)
from app.ir.vision_event import IRTarget, VisionEvent

TOP_LEVEL_MODELS = [
    # ledger
    Unit,
    TranscriptLedger,
    # template
    CaptionStyle,
    ZoomKeyframe,
    VisualStyle,
    AudioStyle,
    StickerEvent,
    StyleRule,
    Slot,
    Tags,
    TemplateIR,
    # project
    PlacedSegment,
    Caption,
    Gap,
    Section,
    ProjectIR,
    # patch
    Patch,
    # workbench events
    IRTarget,
    VisionEvent,
]


def build_schema() -> dict:
    _, schema = models_json_schema(
        [(m, "validation") for m in TOP_LEVEL_MODELS],
        ref_template="#/$defs/{model}",
        schema_generator=GenerateJsonSchema,
    )
    schema["title"] = "SceneEcho IR"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def export_json_schema(out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = build_schema()
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
