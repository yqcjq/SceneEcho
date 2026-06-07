"""Environment-driven settings. Single source of truth for paths and external endpoints."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    model_vlm: str = Field(default="qwen-vl-max-latest", alias="MODEL_VLM")
    model_text: str = Field(default="claude-opus-4-7", alias="MODEL_TEXT")
    model_text_cheap: str = Field(default="qwen-plus", alias="MODEL_TEXT_CHEAP")

    bgm_strategy: str = Field(default="features", alias="BGM_STRATEGY")
    enable_cli_ingest: bool = Field(default=False, alias="ENABLE_CLI_INGEST")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

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
