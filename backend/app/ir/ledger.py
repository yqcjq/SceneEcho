"""TranscriptLedger — WhisperX word-level timestamps. Immutable text, LLM-only id ops."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Unit(BaseModel):
    id: int
    text: str
    start: float
    end: float
    avg_logprob: float = 0.0


class TranscriptLedger(BaseModel):
    units: list[Unit] = Field(default_factory=list)
    language: str = "zh"
    media_path: str
