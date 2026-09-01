"""Application configuration, loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -----------------------------------------------------------
    # PostgreSQL is the target database. The SQLite default exists so the demo
    # runs with zero infrastructure; point DATABASE_URL at Postgres for any
    # real deployment (see docker-compose.yml).
    database_url: str = "sqlite+pysqlite:///./revenuerecover.db"
    sql_echo: bool = False

    # --- AI provider -------------------------------------------------------
    ai_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    xai_api_key: str | None = None
    # AGENT_MODEL is an optional provider-agnostic override. When omitted,
    # each provider uses its own current default.
    agent_model: str | None = None
    anthropic_model: str = "claude-opus-5"
    xai_model: str = "grok-4.6"
    agent_timeout_seconds: float = Field(default=30, gt=0, le=120)
    agent_max_tool_turns: int = Field(default=6, ge=1, le=10)
    agent_max_tool_calls: int = Field(default=8, ge=1, le=20)

    # --- Recovery policy limits (enforced by the backend, not the AI) -------
    max_payment_retries: int = 2
    max_reminders: int = 3
    contact_cooldown_hours: int = 24
    escalation_amount_threshold: int = 5_000_000  # paise (INR 50,000)
    high_value_ltv_threshold: int = 5_000_000  # paise (INR 50,000)

    # --- App ----------------------------------------------------------------
    app_name: str = "RevenueRecover AI"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
