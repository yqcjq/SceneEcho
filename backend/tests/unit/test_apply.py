"""Unit tests for Phase 2 apply / asr / recommend modules.

Pure-functions and small orchestration paths — no real ASR / VLM.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.ir.template import (
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


@pytest.mark.asyncio
async def test_asr_fallback_uniform_chunks(task_with_events, no_credentials, monkeypatch):
    """When WhisperX is unavailable, ASR degrades to uniform 3s chunks."""
    from app.understand import asr

    task_id, sample_id = task_with_events
    settings = get_settings()
    sample_dir = settings.data_root / "samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    fake_mp4 = sample_dir / "normalized.mp4"
    fake_mp4.write_bytes(b"\x00")

    # Stub get_media_info → duration=10s; stub the whisperx path to raise.
    monkeypatch.setattr(
        asr, "get_media_info", lambda *_a, **_k: {"format": {"duration": 10.0}}
    )

    async def _raise(*_a, **_kw):
        raise ImportError("whisperx not installed")

    monkeypatch.setattr(asr, "_whisperx_run", _raise)

    ledger, events = await asr.transcribe(fake_mp4, task_id=task_id)
    assert len(ledger.units) >= 3  # 10/3 ≈ 3-4 chunks
    assert all(u.text.startswith("[语音") for u in ledger.units)
    # Last Unit ends at or past duration (with rounding tolerance).
    assert ledger.units[-1].end >= 9.9
    # Fallback event is severity=warning
    assert any(e.severity == "warning" for e in events)


def test_slot_speed_clamp_bounds():
    """_clamp_speed enforces ±20%."""
    from app.apply.mapping import _clamp_speed

    assert _clamp_speed(1.5) == 1.2
    assert _clamp_speed(0.5) == 0.8
    assert abs(_clamp_speed(1.0) - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_gaps_classify_by_material_req(task_with_events):
    """detect_gaps tags voice gaps text_fill and B-roll gaps wrap_fill."""
    from app.apply.gaps import detect_gaps

    task_id, _ = task_with_events
    template = TemplateIR(
        id="tpl_gap",
        name="gap test",
        source_sample="smp_gap",
        skeleton=[
            Slot(role="开头", material_req="人物口播", style=StyleRule(caption=CaptionStyle())),
            Slot(role="主体", material_req="B-roll/包装", style=StyleRule()),
        ],
        tags=Tags(),
    )
    # No segments → both slots are gaps.
    gaps, _ = await detect_gaps([], template, task_id=task_id)
    assert len(gaps) == 2
    assert gaps[0].fill_strategy == "text_fill"
    assert gaps[1].fill_strategy == "wrap_fill"


def test_preview_props_shape_matches_ir():
    """Sanity: ProjectIR.degraded round-trips through JSON."""
    from app.ir.project import ProjectIR

    ir = ProjectIR(
        project_id="prj_x",
        user_material="projects/prj_x/normalized.mp4",
        sections=[],
        captions=[],
        bgm_track="system/bgm_pool/calm_120.mp3",
        degraded={"sections.0.segments": "ValueError: empty"},
    )
    data = ir.model_dump_json()
    ir2 = ProjectIR.model_validate_json(data)
    assert ir2.bgm_track == "system/bgm_pool/calm_120.mp3"
    assert ir2.degraded == {"sections.0.segments": "ValueError: empty"}


# ---------------------------------------------------------------------------
# Unit splitter — 用户报告的"8s 100 字一条字幕"退化复盘 (PLAN 模板推荐ASR)
# ---------------------------------------------------------------------------


def _word_seg(words):
    """Build a WhisperX-style segment from (text, start, end[, prob]) tuples."""
    payload = []
    for tup in words:
        text, start, end = tup[0], tup[1], tup[2]
        prob = tup[3] if len(tup) > 3 else 0.9
        payload.append({"word": text, "start": start, "end": end, "probability": prob})
    return [{"text": "".join(w["word"] for w in payload), "start": payload[0]["start"], "end": payload[-1]["end"], "words": payload}]


def test_unit_splitter_hard_caps_long_unbroken_run():
    """100-char run with no pause → split by max_chars=12 into ≥8 Units."""
    from app.understand.asr import _segments_to_units

    # 100 single-character words, each 0.1s apart (gap=0 between consecutive).
    chars = "零一二三四五六七八九"
    words = [(chars[i % 10], i * 0.1, (i + 1) * 0.1) for i in range(100)]
    units = _segments_to_units(_word_seg(words))
    assert 8 <= len(units) <= 14, f"expected 8-14 Units, got {len(units)}"
    for u in units:
        assert len(u.text) <= 12, f"Unit '{u.text}' exceeds max_chars"


def test_unit_splitter_breaks_on_long_pause():
    """Pause > UNIT_GAP_SEC (0.15) AND ≥ min_chars → break."""
    from app.understand.asr import _segments_to_units

    # 5 chars at t=0..0.5, then 0.5s pause, then 5 more chars.
    words = [
        ("你", 0.0, 0.1),
        ("好", 0.1, 0.2),
        ("世", 0.2, 0.3),
        ("界", 0.3, 0.4),
        ("呀", 0.4, 0.5),
        # Big gap here.
        ("我", 1.0, 1.1),
        ("是", 1.1, 1.2),
        ("张", 1.2, 1.3),
        ("三", 1.3, 1.4),
        ("呐", 1.4, 1.5),
    ]
    units = _segments_to_units(_word_seg(words))
    assert len(units) == 2, f"expected 2 Units across pause, got {len(units)}: {[u.text for u in units]}"
    assert units[0].text == "你好世界呀"
    assert units[1].text == "我是张三呐"


def test_unit_splitter_keeps_short_pause():
    """Pause < UNIT_GAP_SEC → no break."""
    from app.understand.asr import _segments_to_units

    words = [
        ("你", 0.0, 0.1),
        ("好", 0.1, 0.2),
        ("世", 0.2, 0.3),
        ("界", 0.3, 0.4),
        # Tiny 0.05s gap — well under 0.15s threshold.
        ("呀", 0.45, 0.55),
    ]
    units = _segments_to_units(_word_seg(words))
    assert len(units) == 1
    assert units[0].text == "你好世界呀"


def test_unit_splitter_holds_when_below_min_chars():
    """Pause after only 2 chars (< min_chars=4) → don't break."""
    from app.understand.asr import _segments_to_units

    words = [
        ("嗯", 0.0, 0.1),
        ("呃", 0.1, 0.2),
        # Big gap, but cur_chars=2 < min_chars=4.
        ("然", 1.0, 1.1),
        ("后", 1.1, 1.2),
        ("我", 1.2, 1.3),
        ("说", 1.3, 1.4),
    ]
    units = _segments_to_units(_word_seg(words))
    # The min_chars guard prevents the early-pause break; 嗯呃 stays glued.
    assert len(units) == 1
    assert units[0].text == "嗯呃然后我说"


def test_unit_splitter_breaks_on_chinese_punctuation():
    """Sentence-ending punctuation triggers a break when accumulated chars ≥ min."""
    from app.understand.asr import _segments_to_units

    words = [
        ("我", 0.0, 0.1),
        ("是", 0.1, 0.2),
        ("张", 0.2, 0.3),
        ("三。", 0.3, 0.4),  # 句号
        ("欢", 0.41, 0.5),
        ("迎", 0.5, 0.6),
    ]
    units = _segments_to_units(_word_seg(words))
    # The 。break fires before 欢 because we've got ≥4 chars accumulated.
    assert len(units) == 2
    assert units[0].text == "我是张三。"
    assert units[1].text == "欢迎"


# ---------------------------------------------------------------------------
# GLM-ASR client (mocked HTTP / settings)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_glm_asr_missing_key_raises(task_with_events, no_credentials, tmp_path):
    """No LLM_API_KEY → GLMASRMissingKey, no HTTP call."""
    from app.understand import glm_asr

    task_id, _ = task_with_events
    fake_wav = tmp_path / "audio.wav"
    fake_wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

    with pytest.raises(glm_asr.GLMASRMissingKey):
        await glm_asr.transcribe_glm(fake_wav, task_id=task_id)


@pytest.mark.asyncio
async def test_glm_asr_too_long_raises(task_with_events, monkeypatch, tmp_path):
    """ffprobe duration > 30s → GLMASRTooLong before any HTTP call."""
    from app.understand import glm_asr

    task_id, _ = task_with_events
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    fake_wav = tmp_path / "audio.wav"
    fake_wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    monkeypatch.setattr(
        glm_asr, "get_media_info", lambda *_a, **_kw: {"format": {"duration": 60.0}}
    )

    with pytest.raises(glm_asr.GLMASRTooLong):
        await glm_asr.transcribe_glm(fake_wav, task_id=task_id)

    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_glm_asr_happy_path_returns_text(task_with_events, monkeypatch, tmp_path):
    """Mocked PPIO 200 OK → returns text + emits a stage='2.asr.glm' event."""
    import httpx

    from app.event_bus import get_event_bus
    from app.understand import glm_asr

    task_id, _ = task_with_events
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    fake_wav = tmp_path / "audio.wav"
    fake_wav.write_bytes(b"RIFF" + b"\x00" * 1000 + b"WAVEfmt ")
    monkeypatch.setattr(
        glm_asr, "get_media_info", lambda *_a, **_kw: {"format": {"duration": 8.0}}
    )

    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.content
        return httpx.Response(200, json={"text": "你好,我是张三。"})

    transport = httpx.MockTransport(_handler)
    real_client_ctor = httpx.AsyncClient

    def _patched_client(*_a, **kw):
        kw.pop("transport", None)
        return real_client_ctor(transport=transport, **kw)

    monkeypatch.setattr(glm_asr.httpx, "AsyncClient", _patched_client)

    text = await glm_asr.transcribe_glm(fake_wav, task_id=task_id)
    assert text == "你好,我是张三。"
    assert captured["auth"] == "Bearer fake-key"
    assert "/v3/glm-asr" in captured["url"]

    bus = get_event_bus()
    events = bus.replay(task_id)
    glm_events = [e for e in events if e.stage == glm_asr.STAGE]
    assert len(glm_events) == 1
    assert glm_events[0].source == "asr"

    get_settings.cache_clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Apply pipeline ledger reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_reuses_cached_transcript(task_with_events, monkeypatch):
    """When projects/{id}/transcript.json exists, apply_short skips transcribe()."""
    from app import tasks_store
    from app.apply import pipeline as apply_pipeline
    from app.event_bus import get_event_bus
    from app.ir.ledger import TranscriptLedger, Unit
    from app.kb import store as kb_store
    from app.understand import asr as asr_mod

    settings = get_settings()
    project_id = "prj_reuse"
    project_dir = settings.data_root / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    # Empty mp4 placeholder; ffmpeg won't actually run because we stub the
    # downstream stages too.
    (project_dir / "normalized.mp4").write_bytes(b"\x00")

    cached = TranscriptLedger(
        units=[
            Unit(id=0, text="你好", start=0.0, end=0.5, avg_logprob=-0.2),
            Unit(id=1, text="世界", start=0.6, end=1.1, avg_logprob=-0.2),
        ],
        language="zh",
        media_path=f"projects/{project_id}/normalized.mp4",
    )
    (project_dir / "transcript.json").write_text(
        cached.model_dump_json(), encoding="utf-8"
    )

    template = TemplateIR(
        id="tpl_reuse",
        name="reuse test",
        source_sample="smp_reuse",
        skeleton=[
            Slot(role="开头", material_req="人物口播", style=StyleRule(caption=CaptionStyle())),
        ],
        tags=Tags(),
    )
    kb_store.save_template(template)

    transcribe_calls: list[str] = []

    async def _spy(*_a, **_kw):
        transcribe_calls.append("called")
        raise AssertionError("transcribe() should not be called when transcript.json exists")

    monkeypatch.setattr(asr_mod, "transcribe", _spy)
    monkeypatch.setattr(apply_pipeline, "transcribe", _spy)

    # Stub out the downstream heavy stages — we only care that ASR was skipped.
    async def _empty_map(*_a, **_kw):
        return [], []

    async def _empty_gaps(*_a, **_kw):
        return [], []

    async def _empty_style(*_a, **_kw):
        return [], [], None, []

    monkeypatch.setattr(apply_pipeline, "map_short_to_template", _empty_map)
    monkeypatch.setattr(apply_pipeline, "detect_gaps", _empty_gaps)
    monkeypatch.setattr(apply_pipeline, "apply_style", _empty_style)
    monkeypatch.setattr(
        apply_pipeline.ffx, "get_media_info", lambda *_a, **_kw: {"format": {"duration": 1.1}}
    )

    task_id = tasks_store.create_task(
        "apply_short", resource_kind="project", resource_id=project_id
    )
    bus = get_event_bus()
    bus.register_path(task_id, bus.resolve_events_path("project", project_id, task_id))

    ir = await apply_pipeline.apply_short(project_id, template.id, task_id=task_id)

    assert transcribe_calls == [], "transcribe() must not run when transcript.json is reused"
    events = bus.replay(task_id)
    reuse_events = [e for e in events if e.stage.endswith("asr_reuse")]
    assert len(reuse_events) == 1
    assert "2 个 Unit" in reuse_events[0].semantic_label
    assert ir.project_id == project_id
