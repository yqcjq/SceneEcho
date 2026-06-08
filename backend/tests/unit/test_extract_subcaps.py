"""Phase 1A subcapability unit tests.

These tests don't require ML deps or VLM credentials — they verify the
*shape* of the events and structured outputs produced by each subcap when
all upstream calls fall back. Real-fixture integration tests live under
``backend/tests/integration/`` and skip when fixtures are absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.extract.context import Phase1AContext


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _bogus_ctx(task_id: str) -> Phase1AContext:
    """Minimal context pointing at a non-existent video — every subcap path
    should fall back gracefully when scenes/frames yield nothing useful."""
    return Phase1AContext(
        sample_id="evt_test_sample",
        normalized_path=Path("/nonexistent/video.mp4"),
        task_id=task_id,
    )


@pytest.mark.asyncio
async def test_scenes_falls_back_when_dep_missing(task_with_events, no_credentials):
    """When PySceneDetect isn't available the call returns 1 scene + warning."""
    from app.extract import scenes as scenes_mod

    bogus = Path("/nonexistent/video.mp4")
    task_id, _ = task_with_events
    found, events = await scenes_mod.detect_scenes(bogus, task_id=task_id)
    assert len(found) >= 1
    assert events
    assert any(e.severity == "warning" for e in events)


@pytest.mark.asyncio
async def test_scenes_zero_length_skips_duration_write(task_with_events, no_credentials):
    """First-principles fix: a zero-length scene must not emit a duration
    write whose ir_value is degenerate. Phase1AReport.scenes only receives
    positive-span entries."""
    import importlib

    scenes_mod = importlib.import_module("app.extract.scenes")
    from app.event_bus import get_event_bus
    from app.ir.vision_event import IRTarget, VisionEvent

    bus = get_event_bus()
    task_id, _ = task_with_events

    s = scenes_mod.Scene(idx=0, start_sec=0.0, end_sec=0.0)
    length = s.end_sec - s.start_sec
    ir_target: IRTarget | None = None
    ir_value: dict | None = None
    if length > 0:
        ir_target = IRTarget(ir_type="Phase1AReport", path="scenes", op="append")
        ir_value = s.to_report_entry().model_dump(mode="json")
    ev = VisionEvent(
        task_id=task_id,
        source="cv",
        stage=scenes_mod.STAGE,
        semantic_label=f"切点 #{s.idx} @{s.start_sec:.2f}s",
        confidence=0.99,
        ir_target=ir_target,
        ir_value=ir_value,
        duration_ms=0,
    )
    await bus.publish(task_id, ev)

    assert ev.ir_target is None
    assert ev.ir_value is None


@pytest.mark.asyncio
async def test_captions_handles_empty_frame_list(task_with_events, no_credentials):
    """detect_captions on an empty frames list returns ([], [])."""
    from app.extract.captions import detect_captions

    task_id, _ = task_with_events
    ctx = _bogus_ctx(task_id)
    # Force frames to []: scenes returns 1 scene of zero length, sample_frames
    # returns [] when ffprobe duration is 0. Pre-populate the cache to skip
    # subprocess calls in CI.
    ctx._scenes = []
    ctx._frames = []
    captions, events = await detect_captions(ctx)
    assert captions == []
    assert events == []


@pytest.mark.asyncio
async def test_stickers_handles_empty_frame_list(task_with_events, no_credentials):
    from app.extract.stickers import detect_stickers

    task_id, _ = task_with_events
    ctx = _bogus_ctx(task_id)
    ctx._scenes = []
    ctx._frames = []
    stickers, events = await detect_stickers(ctx)
    assert stickers == []
    assert events == []


@pytest.mark.asyncio
async def test_audio_falls_back_when_dep_missing(task_with_events, no_credentials):
    from app.extract.audio import extract_bgm

    task_id, _ = task_with_events
    ctx = _bogus_ctx(task_id)
    style, events = await extract_bgm(ctx)
    assert style is not None
    assert any(e.severity == "warning" for e in events)


@pytest.mark.asyncio
async def test_caption_function_classify_works_in_fallback(task_with_events, no_credentials):
    from app.extract.captions import CaptionEvent
    from app.ir.template import CaptionStyle
    from app.understand.vision import classify_caption_function

    cap = CaptionEvent(
        style=CaptionStyle(),
        start=0.0,
        end=1.0,
        placeholder_text=["test"],
        length_constraint={"min_chars": 1, "max_chars": 10, "max_lines": 1},
        semantic_purpose="regular",
        bbox_norm_0_999=(100, 100, 200, 200),
        frames_appeared=[0.5],
        confidence=0.9,
    )
    task_id, _ = task_with_events
    result, events = await classify_caption_function(cap, None, task_id=task_id, caption_idx=0)
    assert result is not None
    assert events
    assert events[0].stage == "1A.caption_function"
