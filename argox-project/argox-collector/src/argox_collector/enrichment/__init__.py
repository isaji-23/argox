"""Ingest-time enrichment (GenAI normalisation, cost, residual-PII tagging)."""

from argox_collector.enrichment.pipeline import enrich

__all__ = ["enrich"]
