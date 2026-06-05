"""Collector runtime settings, loaded from environment variables or .env files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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

    # COL-03 Finding 3: Payload size limit (10 MB default for OTLP traces)
    max_payload_size: int = 10 * 1024 * 1024

    storage_backend: str = "local"
    storage_local_root: Path = Path("./var/argox/blobs")
    storage_azure_connection_string: Optional[str] = None
    storage_azure_container: str = "argox"

    index_backend: str = "duckdb"
    index_duckdb_path: Path = Path("./var/argox/index.duckdb")
