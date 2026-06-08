"""Unit tests for EventBus (Phase 0.5)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.config import get_settings
from app.ir.vision_event import VisionEvent


def _make_event(
    stage: str = "0.5.mock", source: str = "system", label: str | None = None
) -> VisionEvent:
    return VisionEvent(
        task_id="__placeholder__",
        source=source,  # type: ignore[arg-type]
        stage=stage,
        semantic_label=label or f"[mock] {stage}",
    )


@pytest.mark.asyncio
async def test_multi_subscriber_broadcast(task_with_events, fresh_event_bus):
    """Three concurrent subscribers each receive every published event."""
    task_id, _ = task_with_events
    queues = [fresh_event_bus.subscribe(task_id) for _ in range(3)]

    ev = _make_event(label="broadcast-1")
    await fresh_event_bus.publish(task_id, ev)

    received = []
    for q in queues:
        item = await asyncio.wait_for(q.get(), timeout=1.0)
        received.append(item)

    assert len(received) == 3
    assert all(r.event_id == ev.event_id for r in received)
    assert all(r.sequence == 1 for r in received)
    assert all(r.task_id == task_id for r in received)


@pytest.mark.asyncio
async def test_replay_from_event_id(task_with_events, fresh_event_bus):
    """replay(from_event_id=X) returns events strictly after X."""
    task_id, _ = task_with_events
    events = []
    for i in range(5):
        ev = _make_event(label=f"replay-{i}")
        await fresh_event_bus.publish(task_id, ev)
        events.append(ev)

    full = fresh_event_bus.replay(task_id)
    assert len(full) == 5
    assert [e.sequence for e in full] == [1, 2, 3, 4, 5]

    after_third = fresh_event_bus.replay(task_id, from_event_id=events[2].event_id)
    assert len(after_third) == 2
    assert [e.semantic_label for e in after_third] == ["replay-3", "replay-4"]

    # Unknown id falls back to full history (safer than silent drop).
    unknown = fresh_event_bus.replay(task_id, from_event_id="does-not-exist")
    assert len(unknown) == 5


@pytest.mark.asyncio
async def test_replay_until_seq_bounds_history(task_with_events, fresh_event_bus):
    """until_seq is the SSE snapshot ceiling — events past it are excluded."""
    task_id, _ = task_with_events
    for i in range(5):
        await fresh_event_bus.publish(task_id, _make_event(label=f"seq-{i}"))

    bounded = fresh_event_bus.replay(task_id, until_seq=3)
    assert [e.sequence for e in bounded] == [1, 2, 3]


@pytest.mark.asyncio
async def test_jsonl_format(task_with_events, fresh_event_bus):
    """Each persisted line is a valid VisionEvent JSON document."""
    task_id, sample_id = task_with_events
    for i in range(3):
        await fresh_event_bus.publish(task_id, _make_event(label=f"jsonl-{i}"))

    path = get_settings().resolve(f"samples/{sample_id}/extracted/events_{task_id}.jsonl")
    assert path.exists()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3
    for ln in lines:
        ev = VisionEvent.model_validate_json(ln)
        assert ev.task_id == task_id
        assert ev.sequence > 0
    for ln in lines:
        json.loads(ln)


@pytest.mark.asyncio
async def test_sequence_monotonic_under_concurrency(task_with_events, fresh_event_bus):
    """Concurrent publishes still produce a 1..N monotonic sequence."""
    task_id, _ = task_with_events

    async def pub(i: int) -> None:
        await fresh_event_bus.publish(task_id, _make_event(label=f"concurrent-{i}"))

    await asyncio.gather(*(pub(i) for i in range(10)))

    full = fresh_event_bus.replay(task_id)
    assert [e.sequence for e in full] == list(range(1, 11))


@pytest.mark.asyncio
async def test_subscribe_with_snapshot_no_overlap(task_with_events, fresh_event_bus):
    """subscribe_with_snapshot atomically returns the high-water mark.

    Pre-snapshot events are in the JSONL; post-snapshot events arrive on
    the queue. The two sets do not overlap — SSE consumers therefore do
    not need any sequence-based dedup logic.
    """
    task_id, _ = task_with_events
    for i in range(3):
        await fresh_event_bus.publish(task_id, _make_event(label=f"pre-{i}"))

    queue, snapshot = await fresh_event_bus.subscribe_with_snapshot(task_id)
    assert snapshot == 3

    for i in range(2):
        await fresh_event_bus.publish(task_id, _make_event(label=f"post-{i}"))

    received = []
    for _ in range(2):
        ev = await asyncio.wait_for(queue.get(), timeout=1.0)
        received.append(ev)
    assert [e.sequence for e in received] == [4, 5]
    assert [e.semantic_label for e in received] == ["post-0", "post-1"]

    history = fresh_event_bus.replay(task_id, until_seq=snapshot)
    assert [e.semantic_label for e in history] == ["pre-0", "pre-1", "pre-2"]


@pytest.mark.asyncio
async def test_counter_resumes_from_jsonl_tail(task_with_events):
    """After a process restart, publish resumes from the JSONL's last seq.

    Previously the counter was rebuilt from a SQL column that could lag the
    JSONL on a write-then-crash; reading the JSONL tail eliminates that
    drift entirely.
    """
    from app import event_bus as eb

    task_id, sample_id = task_with_events
    bus_a = eb.get_event_bus()
    for i in range(5):
        await bus_a.publish(task_id, _make_event(label=f"pre-{i}"))

    # Simulate a restart: drop the in-memory counter and queue maps; the
    # JSONL file plus the tasks-store row stay on disk.
    eb.reset_event_bus()
    bus_b = eb.get_event_bus()
    bus_b.register_path(
        task_id,
        eb.EventBus.resolve_events_path("sample", sample_id, task_id),
    )

    ev = _make_event(label="post-restart")
    await bus_b.publish(task_id, ev)
    assert ev.sequence == 6


def test_resolve_events_path():
    """Path scheme B: sample / project / template route to dedicated dirs."""
    from app.event_bus import EventBus

    assert (
        EventBus.resolve_events_path("sample", "smp_001", "task_a")
        == "samples/smp_001/extracted/events_task_a.jsonl"
    )
    assert (
        EventBus.resolve_events_path("project", "prj_001", "task_b")
        == "projects/prj_001/pipeline/events_task_b.jsonl"
    )
    template_path = EventBus.resolve_events_path("template", "tpl_001", "task_c")
    assert template_path.startswith("system/dev_events/template_tpl_001/")
    assert template_path.endswith("events_task_c.jsonl")


@pytest.mark.asyncio
async def test_silent_mode_via_client(task_with_events, fresh_event_bus):
    """LLMClient.chat_vision(silent=True) skips event_bus.publish."""
    from pydantic import BaseModel

    from app.llm.client import OpenAICompatClient

    class _S(BaseModel):
        pass

    task_id, _ = task_with_events
    queue = fresh_event_bus.subscribe(task_id)

    client = OpenAICompatClient()
    _, events = await client.chat_vision(
        messages=[],
        model="qwen-vl-max-latest",
        stage="0.5.silent",
        task_id=task_id,
        frames=None,
        ir_target_template=None,
        schema=_S,
        silent=True,
    )

    # The client still synthesises an event for caller use, but the bus stays clean.
    assert len(events) == 1
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.2)


@pytest.mark.asyncio
async def test_unsubscribe_removes_subscriber(task_with_events, fresh_event_bus):
    task_id, _ = task_with_events
    q = fresh_event_bus.subscribe(task_id)
    fresh_event_bus.unsubscribe(task_id, q)
    # Publishing afterwards must not raise and must not leave the queue full.
    await fresh_event_bus.publish(task_id, _make_event(label="post-unsub"))
    assert q.empty()
