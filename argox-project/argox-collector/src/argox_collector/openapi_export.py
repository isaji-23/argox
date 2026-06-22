"""Canonical OpenAPI export for the Collector contract.

The committed ``openapi.json`` is the single source of truth that feeds the
dashboard's typed TypeScript client (COL-10). Both the ``export-openapi`` CLI
and the contract test serialize the schema through :func:`render_openapi` so
they can never disagree on formatting and produce spurious drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Committed contract file, resolved relative to the package source tree:
# ``src/argox_collector/openapi_export.py`` -> package root holding the JSON.
DEFAULT_OPENAPI_PATH = (
    Path(__file__).resolve().parents[2] / "openapi.json"
)


def build_openapi() -> dict[str, Any]:
    """Return the live OpenAPI schema of a freshly built Collector app."""
    # Imported lazily so this module stays importable without constructing an
    # app (e.g. when only ``DEFAULT_OPENAPI_PATH`` is needed).
    from argox_collector.app import create_app

    return create_app().openapi()


def render_openapi(schema: dict[str, Any]) -> str:
    """Serialize a schema to the canonical on-disk form.

    Sorted keys and a trailing newline keep the committed file stable and
    diff-friendly regardless of dict insertion order.
    """
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"
