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
    # NOTE: binds all interfaces, which is intended for containerised deploys
    # but leaves the endpoint exposed since auth is not yet in place. Tighten
    # to 127.0.0.1, or front with auth, once COL-09 lands.
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    storage_backend: str = "local"
    storage_local_root: Path = Path("./var/argox/blobs")
    storage_azure_connection_string: Optional[str] = None
    storage_azure_container: str = "argox"

    index_backend: str = "duckdb"
    index_duckdb_path: Path = Path("./var/argox/index.duckdb")

    enrichment_enabled: bool = True
    pricing_table_path: Optional[Path] = None

    # Audit log (COL-08): blob key prefix for WORM segments and the per-segment
    # record cap that triggers rollover to a new segment.
    audit_log_prefix: str = "audit-log"
    audit_segment_max_records: int = 1000

    # Comma-separated list of origins allowed to call the API from a browser
    # (e.g. "https://dashboard.example.com,http://localhost:5173"). Kept as a
    # plain string so the value can be passed through a single environment
    # variable; empty means CORS middleware is not installed at all.
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Return ``cors_origins`` parsed into a list of non-empty origins."""
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    # Maximum accepted request body size in bytes (default 10 MiB). Requests
    # over this limit are rejected with 413 before the body is fully buffered,
    # bounding memory use under concurrent or malicious uploads.
    max_payload_size: int = 10 * 1024 * 1024
