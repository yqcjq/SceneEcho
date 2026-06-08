"""IR (Intermediate Representation) — pydantic models, single source of truth.

Exports JSON Schema via app.ir.export.export_json_schema() so renderer + frontend
can codegen aligned zod/TS types.
"""

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

__all__ = [
    "AudioStyle",
    "Caption",
    "CaptionStyle",
    "Gap",
    "Patch",
    "PlacedSegment",
    "ProjectIR",
    "Section",
    "Slot",
    "StickerEvent",
    "StyleRule",
    "Tags",
    "TemplateIR",
    "TranscriptLedger",
    "Unit",
    "VisualStyle",
    "ZoomKeyframe",
]
