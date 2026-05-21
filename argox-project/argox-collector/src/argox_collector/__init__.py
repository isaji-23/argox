"""Argox Collector — server-side ingestion, indexing and policy distribution service."""

__version__ = "0.1.0"

from argox_collector.app import create_app
from argox_collector.settings import CollectorSettings

__all__ = ["CollectorSettings", "create_app"]
