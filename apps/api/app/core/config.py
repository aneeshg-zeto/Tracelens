from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[4] if len(_HERE.parents) > 4 else _HERE.parents[-1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    tracelens_env: Literal["development", "test", "production"] = "development"
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    internal_jwt_secret: SecretStr = Field(min_length=32)
    internal_jwt_issuer: str = "tracelens-web"
    internal_jwt_audience: str = "tracelens-api"

    cors_allowed_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    ingest_rate_limit_per_minute: int = 600
    max_request_bytes: int = 5 * 1024 * 1024
    default_capture_payloads: bool = False
    default_retention_days: int = 30
    pricing_file: str | None = None

    integration_encryption_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_provider: Literal["openai", "anthropic"] | None = None
    llm_model: str | None = None

    @field_validator(
        "pricing_file",
        "llm_provider",
        "llm_model",
        "integration_encryption_key",
        "openai_api_key",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        raise ValueError("DATABASE_URL must be a PostgreSQL URL")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
