"""Environment-driven settings. Single source of truth for paths and external endpoints."""

from __future__ import annotations

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


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.data_root.is_absolute():
        s.data_root = (REPO_ROOT / s.data_root).resolve()
    return s
