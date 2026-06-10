"""VisionEvent — AI 决策事件 IR.

Every AI decision (VLM / Text LLM / ASR / audio / CV) emits one of these,
broadcast through ``app.event_bus`` to the SSE workbench.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds")


def _new_event_id() -> str:
    return uuid.uuid4().hex


class IRTarget(BaseModel):
    """Pointer into an IR tree, lodash get/set style.

    The ``path`` is a dot+bracket string consumed by ``lodash.get/set`` on the
    frontend (e.g. ``"skeleton.slots[1].style.caption"``).
    """

    ir_type: Literal["TemplateIR", "ProjectIR", "TranscriptLedger", "Phase1AReport"]
    path: str
    field: str | None = None
    op: Literal["set", "append", "remove"] = "set"


class VisionEvent(BaseModel):
    """Structured record of one AI decision (D13).

    Fields cover the three workbench panes: which frame the AI looked at
    (``frame_url`` + ``bbox_norm``), what it reasoned (``reasoning`` +
    ``semantic_label`` + ``confidence``), and where it wrote into the IR
    (``ir_target`` + ``ir_value``). Stage prefixes follow the naming table in
    PLAN.md ("AI 调用协议·stage 命名规范").

    Two timing axes (Phase 2.6):

    - ``frame_ts`` / wall-clock — when (in real time, via the event bus
      sequence) the AI ran. Powers the gantt view.
    - ``media_ts`` / ``media_ts_range`` — what video moment the AI was
      reasoning about. Powers the media-timeline view. Single-anchor
      events fill ``media_ts`` (e.g. one caption detection in a frame);
      span events fill ``media_ts_range`` (e.g. tagging that looked at
      first/middle/last frames). System / progress events leave both null.
    """

    event_id: str = Field(default_factory=_new_event_id)
    task_id: str
    sequence: int = 0  # filled by EventBus.publish atomically
    timestamp: str = Field(default_factory=_now_iso)
    duration_ms: int = 0
    source: Literal["vlm", "cv", "asr", "audio", "text_llm", "system"]
    model_used: str | None = None
    stage: str
    frame_ts: float | None = None
    frame_url: str | None = None
    bbox_norm: tuple[float, float, float, float] | None = None
    media_ts: float | None = None
    media_ts_range: tuple[float, float] | None = None
    semantic_label: str
    reasoning: str = ""
    confidence: float = 1.0
    ir_target: IRTarget | None = None
    # ``ir_value`` is whatever the AI wants written at ``ir_target.path`` —
    # the IR field at that path may be a scalar (str/int/bool), a list, or a
    # nested dict, so the type must be open. Frontend ``lodash.set`` writes
    # whatever value arrives; pydantic ``model_validate`` accepts ``Any``.
    # Phase 2.6 invariant: ``ir_value`` is also populated for chat_vision
    # call events without an ``ir_target`` (carrying the raw structured
    # output) so ReplayClient can reconstruct results from any recorded
    # event without a separate "emitter" marker.
    ir_value: Any = None
    parent_event_id: str | None = None
    cost_tokens: int | None = None
    confidence_warning: bool = False
    severity: Literal["info", "warning", "error"] = "info"
