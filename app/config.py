"""Single source of environment configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-backed settings. Secrets never have code defaults that are real keys."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="production", description="development enables debug helpers")
    log_level: str = Field(default="INFO")
    database_url: str = Field(
        default="",
        description="Supabase session pooler URL with postgresql+asyncpg:// scheme",
    )

    gemini_api_keys: str = Field(
        default="",
        description="Comma-separated Gemini keys, each from a different GCP project",
    )
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    # Names are confirmed against AI Studio before Phase 3; empty is fine until then.
    gemini_model: str = Field(default="")
    gemini_fallback_model: str = Field(default="")
    gemini_reasoning_effort: str = Field(default="none")
    llm_timeout_seconds: float = Field(default=8)
    llm_temperature: float = Field(default=0.5)
    llm_max_tokens: int = Field(default=300)

    vapi_server_secret: str = Field(default="")
    vapi_api_key: str = Field(
        default="",
        description="Optional; only for a sync script. Never used at runtime.",
    )

    clinic_name: str = Field(default="Maple Grove Family Health")
    clinic_timezone: str = Field(default="America/New_York")

    simulate_db_failure: bool = Field(
        default=False,
        description="Ignored unless APP_ENV=development",
    )

    @property
    def is_development(self) -> bool:
        """True when debug helpers (raw payload logs, SIMULATE_DB_FAILURE) may run."""
        return self.app_env.lower() == "development"

    @property
    def gemini_key_list(self) -> list[str]:
        """Parsed Gemini keys with empty entries dropped."""
        return [key.strip() for key in self.gemini_api_keys.split(",") if key.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
