"""Phase 2.6 unit tests — VisionEvent dual-axis + ReplayClient.

The gantt + media-timeline aggregations live on the frontend (see
``frontend/src/lib/aggregateEvents.ts``); their unit tests are in the
frontend's vitest suite. This file covers backend-only invariants.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.ir.vision_event import IRTarget, VisionEvent
from app.llm.client import FrameRef, _media_ts_from_frames
from app.llm.replay_client import ReplayClient, ReplayExhaustedError


# ---------------------------------------------------------------------------
# media_ts derivation
# ---------------------------------------------------------------------------


def test_media_ts_none_for_zero_frames():
    media_ts, media_ts_range = _media_ts_from_frames(None)
    assert media_ts is None
    assert media_ts_range is None


def test_media_ts_single_frame_fills_point():
    frames = [FrameRef(ts=4.5, url="x.jpg")]
    media_ts, media_ts_range = _media_ts_from_frames(frames)
    assert media_ts == pytest.approx(4.5)
    assert media_ts_range is None


def test_media_ts_multiple_frames_fills_span():
    frames = [
        FrameRef(ts=2.0, url="a.jpg"),
        FrameRef(ts=8.0, url="b.jpg"),
        FrameRef(ts=5.0, url="c.jpg"),
    ]
    media_ts, media_ts_range = _media_ts_from_frames(frames)
    assert media_ts is None
    assert media_ts_range == (pytest.approx(2.0), pytest.approx(8.0))


def test_vision_event_default_dual_axis_fields():
    ev = VisionEvent(
        task_id="t",
        source="vlm",
        stage="1A.captions",
        semantic_label="x",
    )
    assert ev.media_ts is None
    assert ev.media_ts_range is None


# ---------------------------------------------------------------------------
# ReplayClient
# ---------------------------------------------------------------------------


class _DummySchema(BaseModel):
    """Strict — extras forbidden so entity events with extra fields fail validation
    (and ReplayClient correctly skips them rather than silently coercing). Mirrors
    the production schemas which all explicitly enumerate their fields."""

    model_config = {"extra": "forbid"}

    captions: list[str] = []


class _OtherSchema(BaseModel):
    sticker_kind: str = ""


@pytest.fixture
def golden_events_path(tmp_path):
    """Build a small recorded jsonl with one matching + one non-matching event."""
    path = tmp_path / "events.jsonl"
    matching = VisionEvent(
        task_id="t-original",
        sequence=1,
        source="vlm",
        stage="1A.captions",
        semantic_label="字幕识别 · 2 条",
        ir_value=_DummySchema(captions=["A", "B"]).model_dump(mode="json"),
    )
    nonmatching_entity = VisionEvent(
        task_id="t-original",
        sequence=2,
        source="vlm",
        stage="1A.captions",
        semantic_label="entity · sticker fragment",
        ir_target=IRTarget(ir_type="Phase1AReport", path="captions", op="append"),
        ir_value={"sticker_kind": "icon"},  # validates _OtherSchema, not _DummySchema
    )
    path.write_text(
        matching.model_dump_json() + "\n" + nonmatching_entity.model_dump_json() + "\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_replay_client_returns_recorded_payload(
    golden_events_path, task_with_events
):
    """First chat_vision call pops the matching event, reconstructs the schema."""
    task_id, _ = task_with_events
    client = ReplayClient(golden_events_path)
    parsed, events = await client.chat_vision(
        messages=[{"role": "system", "content": "_"}],
        model="m",
        stage="1A.captions",
        task_id=task_id,
        frames=None,
        ir_target_template=None,
        schema=_DummySchema,
    )
    assert isinstance(parsed, _DummySchema)
    assert parsed.captions == ["A", "B"]
    assert len(events) == 1
    assert events[0].sequence == 1


@pytest.mark.asyncio
async def test_replay_client_skips_entity_events(
    golden_events_path, task_with_events
):
    """When the head event doesn't validate, ReplayClient skips it and exhausts cleanly."""
    task_id, _ = task_with_events
    client = ReplayClient(golden_events_path)
    # First call consumes the matching event.
    await client.chat_vision(
        messages=[],
        model="m",
        stage="1A.captions",
        task_id=task_id,
        frames=None,
        ir_target_template=None,
        schema=_DummySchema,
    )
    # Second call should exhaust because the next queued event has the
    # wrong schema shape (sticker_kind field, not captions list).
    with pytest.raises(ReplayExhaustedError):
        await client.chat_vision(
            messages=[],
            model="m",
            stage="1A.captions",
            task_id=task_id,
            frames=None,
            ir_target_template=None,
            schema=_DummySchema,
        )


@pytest.mark.asyncio
async def test_replay_client_returns_default_for_fallback(tmp_path, task_with_events):
    """A recorded warning event with ir_value=None becomes a default-constructed schema."""
    task_id, _ = task_with_events
    fallback = VisionEvent(
        task_id="t",
        sequence=1,
        source="vlm",
        stage="1A.captions",
        semantic_label="[fallback]",
        severity="warning",
        ir_value=None,
    )
    path = tmp_path / "events.jsonl"
    path.write_text(fallback.model_dump_json() + "\n", encoding="utf-8")

    client = ReplayClient(path)
    parsed, events = await client.chat_vision(
        messages=[],
        model="m",
        stage="1A.captions",
        task_id=task_id,
        frames=None,
        ir_target_template=None,
        schema=_DummySchema,
    )
    assert isinstance(parsed, _DummySchema)
    assert parsed.captions == []  # default
    assert events[0].severity == "warning"


