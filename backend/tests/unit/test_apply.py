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
