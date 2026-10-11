"""Application configuration (env-driven, validated by pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://aer:aer@localhost:5432/aer"

    api_port: int = 8000
    mcp_port: int = 8765
    mcp_server_url: str = "http://localhost:8765"

    sec_user_agent: str = "AI Equity Research (set-SEC_USER_AGENT-in-.env)"
    edgar_cache_dir: Path = Path("./data/edgar")
    sec_rate_limit_per_sec: int = 8

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_verification_model: str = "claude-opus-5-5"

    embedding_provider: Literal["voyage", "openai"] = "voyage"
    embedding_model: str = "voyage-3"
    embedding_dim: int = Field(default=1024, ge=1)
    voyage_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")

    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_project: str = "ai-equity-research"
    langchain_tracing_v2: bool = False
    langchain_endpoint: str = "https://api.smith.langchain.com"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
