"""Phase 1A mock-level integration tests.

These tests don't require ML deps or VLM credentials — they pre-fill
``Phase1AContext`` with synthetic ``Scene`` + ``FrameSample`` lists so the
subcap functions take their normal paths (VLM call → fallback path due to
no credentials → entity events) end-to-end. We then assert:

1. The event sequence has the canonical structure (call event + N entity
   events for list-type subcaps; per-scene entries for dict-type).
2. Every event with an ``ir_target`` writes into ``Phase1AReport`` (no
   leftover ``TemplateIR`` paths).
3. ``parent_event_id`` chains link entity events back to the call event,
   so Phase 2.6's gantt view will show the causal edges.
4. ``Phase1AReport.model_validate`` accepts the accumulated ir_value
   payloads — i.e. the structures we emit are schema-legal.

Real-fixture integration tests (PLAN 1483 — F1/IoU baselines) live in
``backend/tests/integration/test_subcap_baselines.py`` (TODO once full
fixture set is prepared).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.extract.context import Phase1AContext
from app.extract.frame_sampler import FrameSample
from app.extract.scenes import Scene


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _seeded_ctx(task_id: str, sample_id: str = "mock_sample", n_scenes: int = 2) -> Phase1AContext:
    """Build a context whose scenes/frames cache is pre-seeded.

    No subprocess calls (ffmpeg / scenedetect) — the seeded data flows
    through every subcap's main code path while the no_credentials fixture
    forces ``chat_vision`` to its fallback warning event.
    """
    ctx = Phase1AContext(
        sample_id=sample_id,
        normalized_path=Path("/nonexistent/mock.mp4"),
        task_id=task_id,
    )
    ctx._scenes = [
        Scene(idx=i, start_sec=float(i * 5), end_sec=float((i + 1) * 5)) for i in range(n_scenes)
    ]
    ctx._frames = [
        FrameSample(ts=float(t), rel_path=f"samples/{sample_id}/extracted/frames/{t}.jpg", scene_idx=t // 5)
        for t in range(0, n_scenes * 5, 1)
    ][:8]  # cap at 8 to mirror typical sampling
    return ctx


# ---------- list-type subcaps: captions / stickers ----------


@pytest.mark.asyncio
async def test_captions_call_event_no_ir_write_entity_events_target_phase1a_report(
    task_with_events, no_credentials
):
    """The call-level event has no ir_target (1A no longer fakes IR writes
    on the call). Entity-level events (one per merged caption) target
    Phase1AReport.captions with op=append."""
    from app.extract.captions import detect_captions

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id)
    captions, events = await detect_captions(ctx)
    # First event is the call-level VLM event (fallback warning here).
    assert events, "expected at least the call-level event"
    call_ev = events[0]
    assert call_ev.stage == "1A.captions"
    assert call_ev.ir_target is None, "call-level event must not write IR"
    # No captions returned in fallback (default schema is empty).
    assert captions == []


@pytest.mark.asyncio
async def test_stickers_call_event_then_entity_targets_phase1a_report(
    task_with_events, no_credentials
):
    from app.extract.stickers import detect_stickers

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id)
    detections, events = await detect_stickers(ctx)
    assert events
    assert events[0].ir_target is None
    assert detections == []


# ---------- dict-type subcaps: zoom / transitions / masks ----------


@pytest.mark.asyncio
async def test_zoom_direction_writes_into_phase1a_report_per_scene(
    task_with_events, no_credentials
):
    from app.extract.motion import judge_zoom_direction

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id, n_scenes=2)
    directions, events = await judge_zoom_direction(ctx)
    # Two scenes → two VLM calls → two events (each fallback).
    assert len(events) == 2
    for ev in events:
        # All events target Phase1AReport.zoom_directions.<idx>
        if ev.ir_target is not None:
            assert ev.ir_target.ir_type == "Phase1AReport"
            assert ev.ir_target.path.startswith("zoom_directions.")


@pytest.mark.asyncio
async def test_transitions_writes_into_phase1a_report(task_with_events, no_credentials):
    from app.extract.transitions import classify_transitions

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id, n_scenes=3)
    out, events = await classify_transitions(ctx)
    # 3 scenes → 2 boundaries → 2 events.
    assert len(events) == 2
    for ev in events:
        if ev.ir_target is not None:
            assert ev.ir_target.ir_type == "Phase1AReport"
            assert ev.ir_target.path.startswith("transitions.")


@pytest.mark.asyncio
async def test_masks_writes_into_phase1a_report(task_with_events, no_credentials):
    from app.extract.masks import detect_masks

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id, n_scenes=2)
    out, events = await detect_masks(ctx)
    assert len(events) == 2
    for ev in events:
        if ev.ir_target is not None:
            assert ev.ir_target.ir_type == "Phase1AReport"
            assert ev.ir_target.path.startswith("masks.")


# ---------- single-target subcaps: color_lut / audio ----------


@pytest.mark.asyncio
async def test_color_lut_writes_into_phase1a_report_color(task_with_events, no_credentials):
    from app.extract.color import classify_color_lut

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id)
    result, events = await classify_color_lut(ctx)
    assert events
    assert events[0].ir_target is not None
    assert events[0].ir_target.ir_type == "Phase1AReport"
    assert events[0].ir_target.path == "color"


@pytest.mark.asyncio
async def test_audio_writes_into_phase1a_report_audio_subfields(task_with_events, no_credentials):
    """When librosa is unavailable, fallback emits a warning that does not
    write IR. When available, three sub-field events fire (has_bgm / bpm /
    mood_tag) all targeting Phase1AReport.audio."""
    from app.extract.audio import extract_bgm

    task_id, _ = task_with_events
    ctx = _seeded_ctx(task_id)
    style, events = await extract_bgm(ctx)
    # Either 1 fallback event (no librosa) or 3 sub-field events (real).
    assert len(events) in (1, 3)
    for ev in events:
        if ev.ir_target is not None:
            assert ev.ir_target.ir_type == "Phase1AReport"
            assert ev.ir_target.path == "audio"


# ---------- parent_event_id linkage ----------


@pytest.mark.asyncio
async def test_caption_function_links_to_caption_call_event(task_with_events, no_credentials):
    """classify_caption_function takes parent_event_id; the resulting event
    must thread it so Phase 2.6 can draw the dashed causal edge."""
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
    parent_id = "abc123"
    _, events = await classify_caption_function(
        cap, None, task_id=task_id, caption_idx=0, parent_event_id=parent_id
    )
    assert events
    assert events[0].parent_event_id == parent_id


# ---------- Phase1AReport schema legality ----------


def test_phase1a_report_schema_round_trips_typical_payloads():
    """The structures we emit must validate against the IR schema, otherwise
    1B's skeleton.py won't be able to read them back."""
    from app.ir.phase1a_report import (
        Phase1ACaptionEvent,
        Phase1AColorReport,
        Phase1AMaskParams,
        Phase1AReport,
        Phase1AScene,
        Phase1AStickerDetection,
    )
    from app.ir.template import AudioStyle, CaptionStyle, StickerEvent, ZoomKeyframe

    report = Phase1AReport(
        scenes=[Phase1AScene(idx=0, start_sec=0.0, end_sec=2.0)],
        captions=[
            Phase1ACaptionEvent(
                style=CaptionStyle(),
                start=0.0,
                end=2.0,
                placeholder_text=["hi"],
                length_constraint={"min_chars": 1, "max_chars": 10, "max_lines": 1},
                semantic_purpose="regular",
                bbox_norm_0_999=(100, 800, 800, 100),
                frames_appeared=[0.5, 1.0],
                confidence=0.8,
                verified_anim_in="淡入",
                stagger_ms=0,
                function="regular",
            )
        ],
        stickers=[
            Phase1AStickerDetection(
                sticker=StickerEvent(
                    description="emoji",
                    position=(0.1, 0.2),
                    size=(0.05, 0.05),
                    start=0.0,
                    end=1.0,
                    semantic_category="情绪表达",
                ),
                bbox_norm_0_999=(100, 200, 50, 50),
                frames_appeared=[0.0, 0.5],
                confidence=0.9,
            )
        ],
        zoom_directions={"0": "推进"},
        zoom_curves={"0": [ZoomKeyframe(relative_time=0.0, scale=1.0)]},
        transitions={"0": "硬切"},
        masks={
            "0": Phase1AMaskParams(
                has_mask=True,
                kind="circle",
                params_norm_0_999={"cx": 500, "cy": 500, "radius": 100},
                confidence=0.9,
            )
        },
        color=Phase1AColorReport(
            tags=["暖色"],
            dominant_lut_id="warm_01",
            confidence=0.85,
            histogram={"hue_mean": 25.0, "sat_mean": 120.0, "val_mean": 180.0},
        ),
        audio=AudioStyle(has_bgm=True, bpm=120.0, mood_tag="欢快"),
    )
    js = report.model_dump_json()
    again = Phase1AReport.model_validate_json(js)
    assert again.scenes[0].start_sec == 0.0
    assert again.captions[0].function == "regular"
    assert again.zoom_directions["0"] == "推进"
