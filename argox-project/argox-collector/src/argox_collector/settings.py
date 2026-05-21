"""Collector runtime settings, loaded from environment variables or .env files."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CollectorSettings(BaseSettings):
    """Configuration for the Argox Collector service.

    Values are sourced from environment variables prefixed with ``ARGOX_`` or
    from a ``.env`` file in the working directory. All fields are optional and
    fall back to development-friendly defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="ARGOX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "argox-collector"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
