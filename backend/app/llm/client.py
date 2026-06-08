"""LLM/VLM client protocol (D13).

Every AI client method must:
1. Take ``stage``, ``task_id``, ``ir_target_template`` and a pydantic ``schema``;
2. Time itself with ``time.perf_counter()`` and write ``duration_ms`` onto the
   emitted VisionEvent — caller code is zero-touch;
3. Return ``tuple[BaseModel, list[VisionEvent]]`` so callers can react to the
   resulting events without re-querying the bus.

Phase 0.5 ships only stub bodies — they emit one mock event per call and
return a default-constructed instance of the requested schema. Phase 1A swaps
in the real OpenAI / Anthropic implementations.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from app.config import get_settings
from app.event_bus import get_event_bus
from app.ir.vision_event import IRTarget, VisionEvent


class FrameRef(BaseModel):
    ts: float
    url: str
    scene_idx: int | None = None


class LLMClient(ABC):
    """Abstract client. Concrete subclasses must implement chat_vision/chat_text."""

    @abstractmethod
    async def chat_vision(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        frames: Sequence[FrameRef] | None,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]: ...

    @abstractmethod
    async def chat_text(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]: ...


# ----------------------------------------------------------------------
# Phase 0.5 placeholder implementation. Mocks the contract, no API calls.
# ----------------------------------------------------------------------
async def _emit_mock_event(
    *,
    source: str,
    stage: str,
    task_id: str,
    model: str,
    frames: Sequence[FrameRef] | None,
    ir_target: IRTarget | None,
    started_at: float,
    silent: bool,
) -> VisionEvent:
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    frame = frames[0] if frames else None
    event = VisionEvent(
        task_id=task_id,
        source=source,  # type: ignore[arg-type]
        model_used=model,
        stage=stage,
        frame_ts=frame.ts if frame else None,
        frame_url=frame.url if frame else None,
        bbox_norm=None,
        semantic_label=f"[mock] {stage}",
        reasoning="阶段 0.5 占位响应——Phase 1A 接入真实模型。",
        confidence=0.5,
        ir_target=ir_target,
        ir_value=None,
        duration_ms=duration_ms,
        cost_tokens=None,
    )
    if not silent:
        await get_event_bus().publish(task_id, event)
    return event


def _construct_mock(schema: type[BaseModel]) -> BaseModel:
    """Best-effort default instance for the placeholder return value.

    Defaults work when the schema has no required fields; otherwise we fall
    back to ``model_construct`` (no validation) so the caller still gets a
    typed object — Phase 0.5 callers don't read the body.
    """
    try:
        return schema()
    except Exception:  # noqa: BLE001
        return schema.model_construct()


class _StubClient(LLMClient):
    """Shared stub body for both OpenAI and Anthropic placeholders."""

    async def chat_vision(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        frames: Sequence[FrameRef] | None,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        started = time.perf_counter()
        event = await _emit_mock_event(
            source="vlm",
            stage=stage,
            task_id=task_id,
            model=model,
            frames=frames,
            ir_target=ir_target_template,
            started_at=started,
            silent=silent,
        )
        return _construct_mock(schema), [event]

    async def chat_text(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        started = time.perf_counter()
        event = await _emit_mock_event(
            source="text_llm",
            stage=stage,
            task_id=task_id,
            model=model,
            frames=None,
            ir_target=ir_target_template,
            started_at=started,
            silent=silent,
        )
        return _construct_mock(schema), [event]


class OpenAICompatClient(_StubClient):
    """OpenAI-compatible (Qwen-VL via DashScope, GPT-4o) client placeholder."""


class AnthropicClient(_StubClient):
    """Anthropic native (Claude Sonnet/Opus) client placeholder."""


def get_llm_client(provider: str | None = None) -> LLMClient:
    p = provider or get_settings().model_provider
    if p == "anthropic":
        return AnthropicClient()
    # ``mixed`` returns OpenAI-compat in Phase 0.5; the per-stage routing
    # table lands in Phase 1A.
    return OpenAICompatClient()
