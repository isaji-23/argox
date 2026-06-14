"""Contract tests for the committed OpenAPI schema (COL-10).

These guard the Collector ↔ Dashboard contract without CI: the committed
``openapi.json`` feeds the dashboard's typed TypeScript client, so it must stay
in sync with the live FastAPI schema and keep stable, fully tagged operations.
"""

from __future__ import annotations

from argox_collector.openapi_export import (
    DEFAULT_OPENAPI_PATH,
    build_openapi,
    render_openapi,
)

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


def test_committed_openapi_matches_live_schema() -> None:
    """The committed file must equal the freshly rendered schema.

    On failure, regenerate with ``argox-collector export-openapi`` and run
    ``pnpm run gen:api`` in the dashboard, then commit both.
    """
    assert DEFAULT_OPENAPI_PATH.exists(), (
        f"{DEFAULT_OPENAPI_PATH} missing — run 'argox-collector export-openapi'"
    )
    expected = render_openapi(build_openapi())
    actual = DEFAULT_OPENAPI_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "openapi.json is stale — run 'argox-collector export-openapi' and "
        "regenerate the dashboard client"
    )


def test_every_operation_has_id_and_tags() -> None:
    """Each endpoint needs a stable operationId and at least one tag.

    Operation IDs become TypeScript client method names; tags group them.
    """
    schema = build_openapi()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method not in _HTTP_METHODS:
                continue
            where = f"{method.upper()} {path}"
            assert operation.get("operationId"), f"{where} missing operationId"
            assert operation.get("tags"), f"{where} missing tags"


def test_operation_ids_are_unique() -> None:
    """Duplicate operation IDs would collide in the generated client."""
    schema = build_openapi()
    ids = [
        operation["operationId"]
        for methods in schema["paths"].values()
        for method, operation in methods.items()
        if method in _HTTP_METHODS
    ]
    assert len(ids) == len(set(ids)), f"duplicate operationIds: {ids}"
