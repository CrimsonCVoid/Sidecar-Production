"""Server configuration loaded from .env via pydantic-settings (D-05)."""

from __future__ import annotations

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file.

    Required fields (supabase_url, supabase_anon_key, supabase_service_role_key)
    must be present in the environment or .env file.  Optional fields have
    sensible defaults for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    storage_bucket: str = "pipeline-outputs"
