"""ReplayClient — deterministic LLMClient backed by a recorded events.jsonl.

Phase 2.6 regression infra: feed a previously-recorded event stream into
the same subcap code paths the real client drives, so a code change that
shifts an IR field's *shape* (renamed key / typed-list flip / …) is caught
the next time CI runs ``test_golden_runs.py``.

ReplayClient sits on the ``LLMClient`` interface, so it composes with every
subcap that already takes a client through ``Phase1AContext.client``. No
test harness needs to know it exists — dependency injection via a fixture
is enough.

Mechanics
---------

At construction time, every line of the recorded JSONL is parsed into a
:class:`VisionEvent` and bucketed into ``self._stage_queues[stage]`` (FIFO
deques). On each ``chat_vision`` / ``chat_text`` call:

1. Look up the deque for ``stage``.
2. Pop the *first* head event whose ``ir_value`` validates against the
   call-site schema. Events that don't validate (e.g. captions entity events
   in the ``1A.captions`` queue when the chat_vision call expects
   ``CaptionsRawResult``) are silently dropped from the queue — they belong
   to a subcap-emitted entity that the real bus already re-publishes during
   replay.
3. If the head is a recorded fallback event (``ir_value=None``,
   ``severity="warning"``), return a default-constructed schema. This
   matches the production behaviour of the real client when credentials
   are missing or the upstream errors out.
4. Re-publish the recorded event onto the live ``event_bus`` (using the
   *current* task id) so the replay run still drives the workbench / SSE
   pipeline end to end. The recorded event's ``task_id`` is overwritten —
   the goal is to validate that today's subcap code rebuilds the same
   ``TemplateIR`` from yesterday's structured outputs, not to time-travel
   the workbench.

Why validation-based filtering rather than a new ``emitter`` field
-----------------------------------------------------------------

Adding ``emitter: Literal["client", "subcap"]`` to ``VisionEvent`` would
mean a schema migration and code touchpoints in every subcap that
publishes directly. The shape-of-``ir_value`` invariant is already strong
enough to distinguish: chat_vision events carry the call's response
schema (e.g. ``CaptionsRawResult``); subcap-emitted entity events carry
the entity schema (e.g. ``Phase1ACaptionEvent``). pydantic
``model_validate`` separates them deterministically.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.event_bus import get_event_bus
from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, LLMClient, _construct_default
from app.logging import get_logger

log = get_logger(__name__)


class ReplayExhaustedError(RuntimeError):
    """Raised when a chat_vision call has no matching recorded event left.

    Carries the stage and remaining-queue length so test failures can point
    at exactly where the replay diverged from the recording. Callers
    typically don't catch this — the regression test surfaces the failure
    directly.
    """

    def __init__(self, stage: str, remaining: int):
        super().__init__(
            f"replay exhausted for stage={stage!r}: "
            f"{remaining} non-matching event(s) still in queue"
        )
        self.stage = stage
        self.remaining = remaining


class ReplayClient(LLMClient):
    """LLMClient that returns recorded ``ir_value``s instead of calling LLMs.

    Construction reads the recorded JSONL once. After that ``chat_vision``
    / ``chat_text`` are O(1) on the queue head.
    """

    provider_name = "replay"

    def __init__(self, golden_run_path: str | Path):
        self._stage_queues: dict[str, deque[VisionEvent]] = defaultdict(deque)
        path = Path(golden_run_path)
        if not path.exists():
            raise FileNotFoundError(f"golden_run_path does not exist: {path}")
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                ev = VisionEvent.model_validate_json(line)
            except (ValidationError, ValueError) as e:
                log.warning(
                    "replay.skip_bad_line",
                    path=str(path),
                    error=str(e)[:200],
                )
                continue
            self._stage_queues[ev.stage].append(ev)

    # ------------------------------------------------------------------
    # LLMClient API
    # ------------------------------------------------------------------
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
        parent_event_id: str | None = None,
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        return await self._invoke(
            schema=schema, stage=stage, task_id=task_id, silent=silent
        )

    async def chat_text(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        stage: str,
        task_id: str,
        ir_target_template: IRTarget | None,
        schema: type[BaseModel],
        parent_event_id: str | None = None,
        silent: bool = False,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        return await self._invoke(
            schema=schema, stage=stage, task_id=task_id, silent=silent
        )

    # ------------------------------------------------------------------
    # Core replay loop
    # ------------------------------------------------------------------
    async def _invoke(
        self,
        *,
        schema: type[BaseModel],
        stage: str,
        task_id: str,
        silent: bool,
    ) -> tuple[BaseModel, list[VisionEvent]]:
        """Pop the next recorded event whose ``ir_value`` matches ``schema``.

        Non-matching events get dropped (they're subcap-emitted entities,
        which the bus re-publishes during replay). A fallback event
        (``ir_value=None``, ``severity="warning"``) returns a default
        schema instance — same path the real client takes when API
        credentials are absent.
        """
        queue = self._stage_queues.get(stage)
        if not queue:
            raise ReplayExhaustedError(stage, 0)
        while queue:
            ev = queue.popleft()
            # Recorded fallback — propagate that exact behaviour.
            if ev.ir_value is None:
                if ev.severity == "warning":
                    if not silent:
                        await self._republish(task_id, ev)
                    return _construct_default(schema), [ev]
                # ir_value=None on an info event means "no payload was
                # captured" — skip and try the next. Indicates a gap in
                # how the original chat_vision dumped its payload; let
                # the next match win.
                continue
            try:
                parsed = schema.model_validate(ev.ir_value)
            except (ValidationError, TypeError):
                # Wrong shape — entity event for a different schema, or a
                # warning we can't reconstruct. Skip without re-queueing
                # because no later call would match it either.
                continue
            if not silent:
                await self._republish(task_id, ev)
            return parsed, [ev]
        raise ReplayExhaustedError(stage, 0)

    @staticmethod
    async def _republish(task_id: str, ev: VisionEvent) -> None:
        """Forward the recorded event onto the live bus with a fresh task_id.

        The bus stamps a new ``sequence`` and writes to whichever JSONL the
        live task points at. The recording's original task_id is discarded —
        replay produces its own event stream that callers can compare /
        diff against the recording out-of-band if they want to.
        """
        clone = ev.model_copy(update={"task_id": task_id, "sequence": 0})
        await get_event_bus().publish(task_id, clone)


__all__ = ["ReplayClient", "ReplayExhaustedError"]
