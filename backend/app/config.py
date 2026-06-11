"""Environment-driven settings. Single source of truth for paths and external endpoints."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[REPO_ROOT / ".env", REPO_ROOT / ".env.local"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_root: Path = Field(default=REPO_ROOT / "backend" / "data", alias="DATA_ROOT")
    renderer_url: str = Field(default="http://localhost:8001", alias="RENDERER_URL")
    backend_url: str = Field(default="http://localhost:18521", alias="BACKEND_URL")

    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    model_provider: Literal["openai", "anthropic", "mixed"] = Field(
        default="openai", alias="MODEL_PROVIDER"
    )
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    model_vlm: str = Field(default="qwen-vl-max-latest", alias="MODEL_VLM")
    model_text: str = Field(default="claude-opus-4-7", alias="MODEL_TEXT")
    model_text_cheap: str = Field(default="qwen-plus", alias="MODEL_TEXT_CHEAP")

    # ASR (Phase 2 · understand/asr.py). PLAN 1593 names large-v3 as the
    # production default; smaller variants (tiny/base/small/medium) are
    # dev-friendly overrides via .env.local. Device + compute_type follow
    # WhisperX's load_model signature; CPU + int8 is the laptop preset.
    asr_model: str = Field(default="large-v3", alias="ASR_MODEL")
    asr_device: Literal["cpu", "cuda"] = Field(default="cpu", alias="ASR_DEVICE")
    asr_compute_type: str = Field(default="int8", alias="ASR_COMPUTE_TYPE")

    # ASR provider (Phase 2 后端切换). "glm" = GLM-ASR-2512 via PPIO gateway
    # for high-precision Chinese transcription, then WhisperX wav2vec2 forced
    # alignment for word-level timestamps; "whisperx" = original WhisperX
    # transcribe+align path, kept as fallback for offline dev / no-network.
    # GLM 路径在凭证缺失或调用失败时自动降级到 whisperx,所以默认 glm 安全。
    asr_provider: Literal["glm", "whisperx"] = Field(default="glm", alias="ASR_PROVIDER")
    asr_base_url: str = Field(
        default="https://api.ppio.com/v3/glm-asr", alias="ASR_BASE_URL"
    )
    # Reserved — PPIO endpoint embeds the model in the URL, but switching to
    # 智谱 BigModel 原生 (open.bigmodel.cn/api/paas/v4/audio/transcriptions)
    # or another GLM-ASR variant needs this field.
    model_asr: str = Field(default="glm-asr-2512", alias="MODEL_ASR")

    # Unit segmentation thresholds (used by _words_to_units after alignment).
    # 用户 8s 口播 100 字一条字幕的退化根因是 _UNIT_GAP_SEC=0.3 太宽 —— 流畅
    # 中文口播词间停顿基本 < 0.3s,所有词被合并成一个 Unit。0.15 + 12 字硬上限
    # + 4 字软下限是经验值,实际需要再调可由 .env 覆盖。
    unit_gap_sec: float = Field(default=0.15, alias="UNIT_GAP_SEC")
    unit_max_chars: int = Field(default=12, alias="UNIT_MAX_CHARS")
    unit_min_chars: int = Field(default=4, alias="UNIT_MIN_CHARS")

    # AIGC B-roll generation (Phase 5 · agent/aigc.py). The provider is a
    # text-to-image API (OpenAI-compatible /v1/images/generations on PPIO);
    # agent/aigc.py converts the returned image to mp4 via ffmpeg loop so the
    # consumer (renderer's OffthreadVideo) sees a normal video segment.
    # Motion comes from the slot's zoom_keyframes at render time, not the
    # generation API.
    #
    # Empty provider string disables AIGC entirely — every "AI生成画面" slot
    # then degrades to the reuse fill strategy. api_key + model are the
    # third-party image-gen credentials (separate account from LLM_API_KEY);
    # missing either raises a typed error so apply/fill can fall back visibly
    # instead of silently skipping. max_duration_sec is a protective ceiling
    # on the looped-image clip length so a single AIGC slot doesn't dominate
    # the timeline (decisions/013 代价 2).
    aigc_broll_provider: str = Field(default="", alias="AIGC_BROLL_PROVIDER")
    aigc_broll_api_key: str | None = Field(default=None, alias="AIGC_BROLL_API_KEY")
    aigc_broll_base_url: str = Field(
        default="https://api.ppio.com/openai/v1/images/generations",
        alias="AIGC_BROLL_BASE_URL",
    )
    aigc_broll_model: str = Field(default="", alias="AIGC_BROLL_MODEL")
    aigc_broll_max_duration_sec: float = Field(
        default=6.0, alias="AIGC_BROLL_MAX_DURATION_SEC"
    )

    # HuggingFace cache lives under DATA_ROOT so weights co-locate with the
    # rest of the system's heavy assets (kb.sqlite / system/bgm_pool /
    # system/models — see 001ARCHITECTURE §4). Default is a DATA_ROOT-relative
    # POSIX path; explicit absolute paths (set via env) are honoured as-is.
    # Setting this to "" disables the redirect (HF reverts to its own default
    # under the user home).
    hf_cache_dir: str = Field(default=".cache/huggingface", alias="HF_CACHE_DIR")

    bgm_strategy: str = Field(default="features", alias="BGM_STRATEGY")
    enable_cli_ingest: bool = Field(default=False, alias="ENABLE_CLI_INGEST")
    enable_dev_mock: bool = Field(default=False, alias="ENABLE_DEV_MOCK")
    # NoDecode: pydantic-settings would otherwise json.loads() the raw env string
    # for list[str] fields, which conflicts with the comma-separated convention
    # the validator below implements. NoDecode hands the validator the raw string.
    dual_check_stages: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="DUAL_CHECK_STAGES"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("dual_check_stages", mode="before")
    @classmethod
    def _split_stages(cls, v: object) -> object:
        # env arrives as comma-separated string; tests / direct construction
        # may pass a list — accept both, return list[str].
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    def resolve(self, rel: str | Path) -> Path:
        """Resolve a DATA_ROOT-relative path to an absolute Path."""
        p = Path(rel)
        return p if p.is_absolute() else (self.data_root / p)


def _apply_hf_env(settings: Settings) -> None:
    """Redirect HuggingFace cache into DATA_ROOT.

    huggingface_hub reads ``HF_HOME`` / ``HUGGINGFACE_HUB_CACHE`` at import
    time, so this must run before any ``import whisperx`` /
    ``import huggingface_hub`` in the process. ``get_settings`` (lru_cache)
    is the single entry every code path goes through, so wiring it here
    means there is no new initialization seam to remember.

    Honours pre-existing env: if the operator already exported ``HF_HOME``
    we leave it alone (``setdefault`` semantics). Setting ``hf_cache_dir=""``
    in Settings opts out entirely.
    """
    if not settings.hf_cache_dir:
        return
    cache_path = settings.resolve(settings.hf_cache_dir)
    try:
        cache_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # If we can't create the redirect target, don't blow up boot —
        # HF will fall back to its own default cache dir.
        return
    abs_cache = str(cache_path)
    # HF_HOME is the umbrella var; hub-cache is the specific weights dir.
    # Set both for forward-compat across huggingface_hub releases.
    os.environ.setdefault("HF_HOME", abs_cache)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache_path / "hub"))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.data_root.is_absolute():
        s.data_root = (REPO_ROOT / s.data_root).resolve()
    _apply_hf_env(s)
    return s
