"""Application configuration loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings sourced from `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(..., alias="BOT_TOKEN")
    database_url: str = Field(
        default="sqlite+aiosqlite:///mafia.db", alias="DATABASE_URL"
    )
    admin_id: int = Field(default=0, alias="ADMIN_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Render injects PORT; we fall back to 8080 for local dev.
    web_port: int = Field(default=8080, alias="PORT")

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Convert Render's ``postgres://`` URL into the asyncpg form.

        Render injects ``DATABASE_URL`` as ``postgres://user:pass@host/db``
        (sync driver convention). SQLAlchemy needs an explicit async driver:
        ``postgresql+asyncpg://...``. This keeps local SQLite URLs untouched.
        """
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @property
    def is_admin_configured(self) -> bool:
        return self.admin_id > 0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings. Lazily resolved so importing this module
    does not require a configured environment (useful for tooling/tests)."""
    return Settings()


# Convenience module-level accessor. Callers should use ``get_settings()``
# directly when they want DI; ``settings`` is kept for backward-compat.
settings = get_settings()
