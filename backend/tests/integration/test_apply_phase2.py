"""Phase 2 · apply pipeline integration tests (mock-level).

Covers PLAN 1652-1664 verification items 2-5 + 11 using seeded ledgers /
templates (no real ASR / VLM). Tests guard orchestration logic:

- test_sync.py covered  → :func:`test_caption_sync_under_150ms`
- test_mapping.py       → :func:`test_mapping_speed_clamped_to_pm20pct`
                          :func:`test_mapping_handles_short_and_long_material`
- test_gaps.py          → :func:`test_detect_and_fill_gap_for_uncovered_slot`
- test_canvas.py        → :func:`test_canvas_mismatch_produces_letterbox`
- placeholder utilise   → :func:`test_long_unit_text_does_not_exceed_max_chars_per_line`

These are unit-level orchestration tests; the user runs F1 / IoU baselines
with real fixtures separately (PLAN 1559).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.ir.ledger import TranscriptLedger, Unit
from app.ir.template import (
    AudioStyle,
    CaptionStyle,
    Slot,
    StyleRule,
    Tags,
    TemplateIR,
)


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _make_caption_style(*, max_chars: int = 12, max_chars_per_line: int = 6) -> CaptionStyle:
    return CaptionStyle(
        placeholder_text=["4-6 字 CTA 短语"],
        length_constraint={"min_chars": 2, "max_chars": max_chars, "max_lines": 2},
        semantic_purpose="CTA",
        max_chars_per_line=max_chars_per_line,
        layout="multi",
    )


def _make_template(
    *,
    slots: list[Slot] | None = None,
    has_bgm: bool = False,
    bgm_path: str | None = None,
) -> TemplateIR:
    if slots is None:
        slots = [
            Slot(
                role="开头",
                duration={"min": 1.4, "nominal": 2.0, "max": 3.0},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            ),
            Slot(
                role="主体",
                duration={"min": 3.5, "nominal": 5.0, "max": 7.5},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            ),
            Slot(
                role="结尾",
                duration={"min": 2.0, "nominal": 3.0, "max": 4.5},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            ),
        ]
    return TemplateIR(
        id="tpl_test",
        name="测试模板",
        source_sample="smp_test",
        skeleton=slots,
        audio=AudioStyle(has_bgm=has_bgm, bgm_path=bgm_path),
        tags=Tags(),
    )


def _make_ledger(*, units_spec: list[tuple[str, float, float]]) -> TranscriptLedger:
    units = [
        Unit(id=i, text=t, start=s, end=e, avg_logprob=-0.2)
        for i, (t, s, e) in enumerate(units_spec)
    ]
    return TranscriptLedger(units=units, language="zh", media_path="samples/test/normalized.mp4")


# ---------------------------------------------------------------------------
# 验证 3 · 时长自适应 (PLAN 1655)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mapping_speed_clamped_to_pm20pct(task_with_events, no_credentials):
    """Construct a user material 1.5× longer than the template → speed
    should clamp to ≤1.2× (per PLAN 1586 ±20% rule)."""
    from app.apply.mapping import map_short_to_template

    task_id, _ = task_with_events
    # template 总 nominal ≈ 2+5+3 = 10s.
    template = _make_template()
    # user material 15s (1.5×): 3 units evenly distributed.
    ledger = _make_ledger(
        units_spec=[("开场白对应这一段", 0.0, 5.0), ("中段内容", 5.0, 10.0), ("结尾", 10.0, 15.0)]
    )
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    assert segments, "mapping should produce at least one segment"
    for seg in segments:
        assert 0.8 <= seg.speed <= 1.2, f"speed {seg.speed} out of ±20% band"


@pytest.mark.asyncio
async def test_mapping_handles_short_and_long_material(task_with_events, no_credentials):
    """User material 0.5× shorter → leaves trailing slots as gaps."""
    from app.apply.gaps import detect_gaps
    from app.apply.mapping import map_short_to_template

    task_id, _ = task_with_events
    template = _make_template()
    # 5s user material (half of nominal 10s) — only fills first 1-2 slots.
    ledger = _make_ledger(
        units_spec=[("开场白", 0.0, 2.5), ("接续内容", 2.5, 5.0)]
    )
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    gaps, _ = await detect_gaps(segments, template, task_id=task_id)
    # PLAN 1600: "MVP 通常 Gap 数 ≤ 1"; short material → trailing slot(s) flagged.
    assert len(gaps) >= 1
    # Segments produced should be all bound (no is_fill).
    assert all(not s.is_fill for s in segments)


# ---------------------------------------------------------------------------
# 验证 4 · 缺口补全 (PLAN 1656)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_and_fill_gap_for_uncovered_slot(
    task_with_events, no_credentials
):
    """Pre-construct: slot that can't be satisfied → gap → fill text non-empty."""
    from app.apply.fill import fill_gaps
    from app.apply.gaps import detect_gaps
    from app.apply.mapping import map_short_to_template

    task_id, _ = task_with_events
    # 4 slots, user only covers 2 → 2 gaps.
    slots = [
        Slot(
            role="开头",
            duration={"min": 1.0, "nominal": 1.5, "max": 2.0},
            material_req="人物口播",
            style=StyleRule(caption=_make_caption_style()),
        ),
        Slot(
            role="主体",
            duration={"min": 1.5, "nominal": 2.0, "max": 3.0},
            material_req="人物口播",
            style=StyleRule(caption=_make_caption_style()),
        ),
        Slot(
            role="主体",
            duration={"min": 1.0, "nominal": 2.0, "max": 3.0},
            material_req="B-roll/包装",
            style=StyleRule(),
        ),
        Slot(
            role="结尾",
            duration={"min": 1.0, "nominal": 1.5, "max": 2.0},
            material_req="人物口播",
            style=StyleRule(caption=_make_caption_style()),
        ),
    ]
    template = _make_template(slots=slots)
    ledger = _make_ledger(
        units_spec=[("开场短句", 0.0, 1.5), ("中段内容", 1.5, 3.0)]
    )
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    gaps, _ = await detect_gaps(segments, template, task_id=task_id)
    assert gaps, "should have at least one gap"

    outcomes, _ = await fill_gaps(
        gaps, template, segments, ledger, task_id=task_id, allow_aigc_broll=False
    )
    assert outcomes, "fill must produce one outcome per gap"
    for o in outcomes:
        # Every gap got SOME fill_result — either text (for text_fill) or
        # at least a styling-only segment for wrap_fill / reuse.
        assert o.segment is not None or o.text != ""


# ---------------------------------------------------------------------------
# 验证 11 · placeholder 利用 (PLAN 1663)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_unit_text_does_not_exceed_max_chars_per_line(
    task_with_events, no_credentials
):
    """When Unit.text is far longer than length_constraint.max_chars, the
    caption is line-wrapped via max_chars_per_line so each line stays
    within the constraint. D11: Caption.text never gets truncated.
    """
    from app.apply.mapping import map_short_to_template
    from app.apply.style import apply_style

    task_id, _ = task_with_events
    template = _make_template(
        slots=[
            Slot(
                role="主体",
                duration={"min": 1.0, "nominal": 2.0, "max": 3.0},
                material_req="人物口播",
                style=StyleRule(
                    caption=_make_caption_style(max_chars=4, max_chars_per_line=6)
                ),
            )
        ]
    )
    long_text = "这是一段远远超过模板字幕长度限制的中文文本将由多行布局自然换行展示"
    ledger = _make_ledger(units_spec=[(long_text, 0.0, 2.0)])
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    styled_segs, captions, _bgm, _events = await apply_style(
        segments, template, ledger, task_id=task_id
    )
    # Caption.text must equal Unit.text byte-for-byte (D11 hard rule).
    assert captions, "should emit at least one Caption"
    assert captions[0].text == long_text
    # Style carries max_chars_per_line=6 (renderer handles wrap).
    assert captions[0].style.max_chars_per_line == 6
    assert captions[0].style.layout == "multi"


# ---------------------------------------------------------------------------
# 验证 2 · 字幕同步 (PLAN 1654)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_caption_sync_under_150ms(task_with_events, no_credentials):
    """For a speed=1.0 mapping, caption.start should match Unit.start
    within ±0.15s. (At non-unity speed the mapping intentionally re-times
    captions via the segment speed, so the sync metric is bounded by the
    speed clamp + segment.timeline_start.)"""
    from app.apply.mapping import map_short_to_template
    from app.apply.style import apply_style

    task_id, _ = task_with_events
    template = _make_template(
        slots=[
            Slot(
                role="开头",
                duration={"min": 1.5, "nominal": 2.0, "max": 2.5},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            ),
            Slot(
                role="主体",
                duration={"min": 4.0, "nominal": 5.0, "max": 6.0},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            ),
            Slot(
                role="结尾",
                duration={"min": 2.0, "nominal": 3.0, "max": 4.0},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            ),
        ]
    )
    ledger = _make_ledger(
        units_spec=[
            ("开场白", 0.0, 2.0),
            ("中段内容这一句话比较长", 2.0, 7.0),
            ("结束语", 7.0, 10.0),
        ]
    )
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    _styled, captions, _bgm, _events = await apply_style(
        segments, template, ledger, task_id=task_id
    )
    # speed == 1.0 → caption.start within 0.15s of Unit.start
    # (segment.timeline_start equals first unit.start cumulatively for unit speed).
    pairs = []
    units_by_id = {u.id: u for u in ledger.units}
    for cap in captions:
        # find the unit whose text matches the caption (text == unit.text)
        for u in units_by_id.values():
            if u.text == cap.text:
                pairs.append((cap.start, u.start))
                break
    assert pairs, "no caption-Unit pairings — test setup is wrong"
    diffs = sorted(abs(c - u) for c, u in pairs)
    median = diffs[len(diffs) // 2]
    assert median < 0.15, f"median sync diff {median}s exceeds 0.15s threshold"


# ---------------------------------------------------------------------------
# 验证 5 · canvas 不匹配 (PLAN 1657)
# ---------------------------------------------------------------------------


def test_canvas_mismatch_produces_letterbox(tmp_path, monkeypatch):
    """The Phase 0 ``ffmpeg.normalize`` already implements the letterbox +
    pad scheme. This test just freezes the vf string under the canvas
    mismatch scenario (16:9 source → 9:16 target) so a future refactor
    can't silently regress to a stretching scale.
    """
    from app.render import ffmpeg as ffx

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        # Return a minimal mock CompletedProcess-shaped object.
        class _R:
            stdout = "{}"
            stderr = ""

        return _R()

    monkeypatch.setattr(ffx.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ffx, "get_media_info", lambda *_a, **_k: {"format": {"duration": "10"}}
    )

    src = tmp_path / "16x9.mp4"
    dst = tmp_path / "9x16.mp4"
    src.write_bytes(b"\x00")  # placeholder for the path

    ffx.normalize(src, dst, width=1080, height=1920, fps=30)

    cmd = captured["cmd"]
    vf_idx = cmd.index("-vf")
    vf = cmd[vf_idx + 1]
    # The letterbox / pad pair must both be present and in this order;
    # without them a 16:9 source would be stretched to 9:16.
    assert "force_original_aspect_ratio=decrease" in vf
    assert "pad=1080:1920" in vf
    assert "color=black" in vf


def test_canvas_mismatch_blur_pad_mode(tmp_path, monkeypatch):
    """ISS-013 P2: ``pad_mode='blur'`` produces a filter_complex with split
    + boxblur + overlay (PLAN 1657 "letterbox 居中、背景模糊"). The Phase 2
    user-material upload path uses this mode."""
    from app.render import ffmpeg as ffx

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)

        class _R:
            stdout = "{}"
            stderr = ""

        return _R()

    monkeypatch.setattr(ffx.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ffx, "get_media_info", lambda *_a, **_k: {"format": {"duration": "10"}}
    )
    src = tmp_path / "src.mp4"
    dst = tmp_path / "dst.mp4"
    src.write_bytes(b"\x00")

    ffx.normalize(src, dst, width=1080, height=1920, fps=30, pad_mode="blur")

    cmd = captured["cmd"]
    fc_idx = cmd.index("-filter_complex")
    fc = cmd[fc_idx + 1]
    # Must split the source, blur-cover one branch, fit the other, overlay.
    assert "split=2" in fc
    assert "force_original_aspect_ratio=increase" in fc
    assert "force_original_aspect_ratio=decrease" in fc
    assert "boxblur=" in fc
    assert "overlay=" in fc


# ---------------------------------------------------------------------------
# ISS-013 P1.A · timeline continuity (no gap / no overlap between segments)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mapping_timeline_is_contiguous_for_overlong_user(
    task_with_events, no_credentials
):
    """User material 1.5× the template's voice nominal — even after speed
    clamps to 1.2×, output_span computed on the renderer side
    ((src_end - src_start) / speed) MUST match what mapping advanced
    timeline_cursor by. No more banding-induced overlap.
    """
    from app.apply.mapping import map_short_to_template

    task_id, _ = task_with_events
    template = _make_template()  # nominal sum = 10s
    ledger = _make_ledger(
        units_spec=[("一段开场", 0.0, 5.0), ("一段中段", 5.0, 10.0), ("一段结尾", 10.0, 15.0)]
    )
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    assert len(segments) >= 2
    # For each consecutive pair, segment[i].timeline_start ==
    # segment[i-1].timeline_start + (src_end-src_start)/speed (within rounding).
    for i in range(1, len(segments)):
        prev = segments[i - 1]
        cur = segments[i]
        prev_out = (prev.src_timerange[1] - prev.src_timerange[0]) / prev.speed
        expected_start = prev.timeline_start + prev_out
        assert abs(cur.timeline_start - expected_start) < 0.005, (
            f"timeline drift at seg#{i}: "
            f"prev_end={expected_start:.3f}, cur_start={cur.timeline_start:.3f}"
        )


@pytest.mark.asyncio
async def test_mapping_truncates_src_when_clamped_speed_overshoots_max(
    task_with_events, no_credentials
):
    """When speed is already 1.2× and slot.max would still be exceeded,
    mapping must shorten src_timerange so output_span = slot.max exactly.
    """
    from app.apply.mapping import map_short_to_template
    from app.ir.template import Slot, StyleRule

    task_id, _ = task_with_events
    # Single voice slot, very tight max=2s. User has 6s of audio.
    # raw_speed = 6/2 = 3 → clamp to 1.2 → output 6/1.2 = 5s > max=2 → truncate.
    template = _make_template(
        slots=[
            Slot(
                role="主体",
                duration={"min": 1.0, "nominal": 2.0, "max": 2.0},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            )
        ]
    )
    ledger = _make_ledger(units_spec=[("一段超长内容用来测试截短", 0.0, 6.0)])
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    assert len(segments) == 1
    seg = segments[0]
    output = (seg.src_timerange[1] - seg.src_timerange[0]) / seg.speed
    assert abs(output - 2.0) < 0.05, f"output_span {output} != slot.max=2.0"
    # speed stays clamped at 1.2.
    assert abs(seg.speed - 1.2) < 1e-3


# ---------------------------------------------------------------------------
# ISS-013 P1.B · sticker time remap (slot-local [0,1] → segment-local seconds)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_style_remaps_stickers_to_segment_local_seconds(
    task_with_events, no_credentials
):
    """slot.style.stickers carry [0,1]; PlacedSegment.applied_style.stickers
    must be plain seconds within the segment's output span.
    """
    from app.apply.mapping import map_short_to_template
    from app.apply.style import apply_style
    from app.ir.template import Slot, StickerEvent, StyleRule

    task_id, _ = task_with_events
    sticker = StickerEvent(
        description="dot",
        position=(0.5, 0.5),
        size=(0.1, 0.1),
        start=0.25,  # slot-local [0,1]
        end=0.75,
    )
    template = _make_template(
        slots=[
            Slot(
                role="主体",
                duration={"min": 2.0, "nominal": 4.0, "max": 6.0},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style(), stickers=[sticker]),
            )
        ]
    )
    ledger = _make_ledger(units_spec=[("一段大约 4 秒口播", 0.0, 4.0)])
    segments, _ = await map_short_to_template(ledger, template, task_id=task_id)
    styled, _captions, _bgm, _events = await apply_style(
        segments, template, ledger, task_id=task_id
    )
    assert len(styled) == 1
    seg = styled[0]
    output_span = (seg.src_timerange[1] - seg.src_timerange[0]) / seg.speed
    assert len(seg.applied_style.stickers) == 1
    out_stk = seg.applied_style.stickers[0]
    # Expected segment-local seconds: 0.25 * output_span and 0.75 * output_span
    assert out_stk.start == pytest.approx(0.25 * output_span, abs=0.01)
    assert out_stk.end == pytest.approx(0.75 * output_span, abs=0.01)


# ---------------------------------------------------------------------------
# ISS-013 P1.C · BGM ducking is invoked by the apply pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_pipeline_runs_bgm_mix_when_bgm_selected(
    task_with_events, no_credentials, tmp_path, monkeypatch
):
    """When style.py picks a bgm_track, the pipeline must call
    ffmpeg.mix_bgm and store the ducked mp4 path on ProjectIR.bgm_track.
    """
    from app.apply import pipeline as ap_pipeline
    from app.config import get_settings
    from app.ir.project import ProjectIR
    from app.ir.template import Slot, StyleRule
    from app.kb import store as kb_store

    task_id, _ = task_with_events
    settings = get_settings()

    # Stage a project dir with a fake normalized.mp4 + a fake BGM file in
    # data/system/bgm_pool/ pointed at by template.audio.bgm_path.
    project_id = "prj_bgm_test"
    project_dir = settings.data_root / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "normalized.mp4").write_bytes(b"\x00")
    bgm_rel = "system/bgm_pool/calm.mp3"
    (settings.data_root / "system" / "bgm_pool").mkdir(parents=True, exist_ok=True)
    (settings.data_root / bgm_rel).write_bytes(b"\x00")

    template = _make_template(
        slots=[
            Slot(
                role="主体",
                duration={"min": 1.0, "nominal": 2.0, "max": 3.0},
                material_req="人物口播",
                style=StyleRule(caption=_make_caption_style()),
            )
        ],
        has_bgm=True,
        bgm_path=bgm_rel,
    )
    template.id = "tpl_bgm_test"
    kb_store.save_template(template, last_extract_task_id=task_id)

    # Stub heavy ffmpeg + ASR.
    monkeypatch.setattr(
        ap_pipeline.ffx,
        "get_media_info",
        lambda *_a, **_k: {"format": {"duration": 2.0}},
    )

    async def _fake_transcribe(*_a, **_kw):
        from app.ir.ledger import TranscriptLedger, Unit

        ledger = TranscriptLedger(
            units=[Unit(id=0, text="一段口播", start=0.0, end=2.0, avg_logprob=-0.2)],
            language="zh",
            media_path=f"projects/{project_id}/normalized.mp4",
        )
        return ledger, []

    monkeypatch.setattr(ap_pipeline, "transcribe", _fake_transcribe)

    mix_calls: list[dict] = []

    def _fake_extract_audio(src, dst):
        Path(dst).write_bytes(b"\x00")
        return Path(dst)

    def _fake_mix_bgm(voice, bgm, output, **kw):
        mix_calls.append({"voice": str(voice), "bgm": str(bgm), "out": str(output), **kw})
        Path(output).write_bytes(b"\x00")
        return Path(output)

    monkeypatch.setattr(ap_pipeline.ffx, "extract_audio", _fake_extract_audio)
    monkeypatch.setattr(ap_pipeline.ffx, "mix_bgm", _fake_mix_bgm)

    # Force BGM_STRATEGY=original so style.py just returns audio.bgm_path
    # without touching the bgm_index.json (which we haven't staged).
    monkeypatch.setenv("BGM_STRATEGY", "original")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    ir = await ap_pipeline.apply_short(
        project_id, "tpl_bgm_test", task_id=task_id
    )
    assert isinstance(ir, ProjectIR)
    # mix_bgm called exactly once with the picked BGM as input.
    assert len(mix_calls) == 1
    call = mix_calls[0]
    assert "calm.mp3" in call["bgm"]
    # bgm_track now points at the ducked file.
    assert ir.bgm_track is not None
    assert ir.bgm_track.endswith("bgm_ducked.aac")
