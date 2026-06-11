"""Settings + HF env redirect (PLAN Phase 2 · L1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import Settings, _apply_hf_env, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_settings_exposes_asr_defaults():
    s = Settings()
    assert s.asr_model == "small" or s.asr_model == "large-v3"
    # asr_device + compute_type carry sensible CPU presets.
    assert s.asr_device in ("cpu", "cuda")
    assert s.asr_compute_type in ("int8", "float16", "float32")


def test_settings_asr_model_env_override(monkeypatch):
    monkeypatch.setenv("ASR_MODEL", "tiny")
    monkeypatch.setenv("ASR_DEVICE", "cpu")
    monkeypatch.setenv("ASR_COMPUTE_TYPE", "int8")
    s = Settings()
    assert s.asr_model == "tiny"
    assert s.asr_device == "cpu"
    assert s.asr_compute_type == "int8"


def test_settings_exposes_aigc_broll_defaults():
    """AIGC B-roll fields default to "disabled" (empty provider, 6s ceiling)."""
    s = Settings()
    assert s.aigc_broll_provider == ""
    assert s.aigc_broll_api_key is None
    assert s.aigc_broll_max_duration_sec == 6.0


def test_settings_aigc_broll_env_override(monkeypatch):
    monkeypatch.setenv("AIGC_BROLL_PROVIDER", "ppio")
    monkeypatch.setenv("AIGC_BROLL_API_KEY", "sk-aigc-xyz")
    s = Settings()
    assert s.aigc_broll_provider == "ppio"
    assert s.aigc_broll_api_key == "sk-aigc-xyz"


def test_settings_aigc_max_duration_parses_float(monkeypatch):
    """AIGC_BROLL_MAX_DURATION_SEC arrives as an env string; parsed to float."""
    monkeypatch.setenv("AIGC_BROLL_MAX_DURATION_SEC", "4.5")
    s = Settings()
    assert isinstance(s.aigc_broll_max_duration_sec, float)
    assert s.aigc_broll_max_duration_sec == 4.5


def test_apply_hf_env_points_into_data_root(tmp_path, monkeypatch):
    """HF_HOME / HUGGINGFACE_HUB_CACHE land under DATA_ROOT/.cache/huggingface.

    Sets DATA_ROOT to tmp_path so the test doesn't poison the real
    backend/data/.cache/huggingface dir.
    """
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HF_CACHE_DIR", ".cache/huggingface")
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    s = Settings()
    if not s.data_root.is_absolute():
        s.data_root = Path(str(tmp_path))
    _apply_hf_env(s)

    expected_home = (tmp_path / ".cache" / "huggingface").resolve()
    assert Path(os.environ["HF_HOME"]).resolve() == expected_home
    assert Path(os.environ["HUGGINGFACE_HUB_CACHE"]).resolve() == (
        expected_home / "hub"
    )
    assert expected_home.exists(), "HF cache dir should be mkdir'd by the helper"


def test_apply_hf_env_respects_preexisting_env(tmp_path, monkeypatch):
    """If HF_HOME is already exported, the helper must not overwrite it."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HF_CACHE_DIR", ".cache/huggingface")
    monkeypatch.setenv("HF_HOME", "C:/already/set")
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", "C:/already/set/hub")

    s = Settings()
    if not s.data_root.is_absolute():
        s.data_root = Path(str(tmp_path))
    _apply_hf_env(s)

    # setdefault semantics: pre-existing values must survive.
    assert os.environ["HF_HOME"] == "C:/already/set"
    assert os.environ["HUGGINGFACE_HUB_CACHE"] == "C:/already/set/hub"


def test_apply_hf_env_opt_out_via_empty_string(tmp_path, monkeypatch):
    """``HF_CACHE_DIR=""`` keeps HF on its own default — no env writes."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HF_CACHE_DIR", "")
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    s = Settings()
    if not s.data_root.is_absolute():
        s.data_root = Path(str(tmp_path))
    _apply_hf_env(s)

    # Helper returned early; env stays clean.
    assert "HF_HOME" not in os.environ
    assert "HUGGINGFACE_HUB_CACHE" not in os.environ


def test_get_settings_applies_hf_env(tmp_path, monkeypatch):
    """End-to-end: get_settings is the single entry — HF env is wired here."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("HF_CACHE_DIR", ".cache/huggingface")
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]

    s = get_settings()
    assert s.data_root.is_absolute()
    # Side-effect: HF_HOME must be set after get_settings returns.
    assert "HF_HOME" in os.environ
    assert Path(os.environ["HF_HOME"]).is_relative_to(tmp_path.resolve())
