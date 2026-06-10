"""Decode OTLP/HTTP trace export requests into flattened ``SpanRecord`` rows.

Supports both OTLP transports accepted by ``POST /v1/traces``:

* ``application/x-protobuf`` — binary ``ExportTraceServiceRequest``.
* ``application/json`` — the protobuf JSON mapping.

OTLP/JSON caveat: the OTLP spec encodes ``trace_id``/``span_id`` as lowercase
hex strings, whereas protobuf's canonical JSON mapping encodes ``bytes`` fields
as base64. ``google.protobuf.json_format.Parse`` follows the base64 convention,
so hex-encoded ids from a strict OTLP/JSON client are normalised to base64
before parsing. Protobuf is the primary, lossless transport; JSON is
best-effort.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

from argox_collector import semconv
from argox_collector.index.base import SpanRecord

CONTENT_TYPE_PROTOBUF = "application/x-protobuf"
CONTENT_TYPE_JSON = "application/json"

# OTLP id fields that strict OTLP/JSON encodes as hex but protobuf JSON expects
# as base64.
_HEX_ID_FIELDS = ("traceId", "spanId", "parentSpanId")
_HEX_RE = re.compile(r"\A[0-9a-fA-F]+\Z")


class OtlpDecodeError(ValueError):
    """Raised when an OTLP request body cannot be parsed."""


def decode_request(body: bytes, content_type: str) -> ExportTraceServiceRequest:
    """Parse a raw request body into an ``ExportTraceServiceRequest``.

    Args:
        body: The raw HTTP request body.
        content_type: The request ``Content-Type`` (parameters such as
            ``; charset=utf-8`` are ignored).

    Returns:
        The decoded protobuf message.

    Raises:
        OtlpDecodeError: If the content type is unsupported or the body cannot
            be parsed.
    """
    media_type = content_type.split(";", 1)[0].strip().lower()
    request = ExportTraceServiceRequest()

    if media_type == CONTENT_TYPE_PROTOBUF:
        try:
            request.ParseFromString(body)
        except Exception as exc:  # protobuf raises DecodeError / TypeError
            raise OtlpDecodeError(f"invalid protobuf body: {exc}") from exc
        return request

    if media_type == CONTENT_TYPE_JSON:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise OtlpDecodeError(f"invalid JSON body: {exc}") from exc
        except RecursionError as exc:
            # Pathologically nested JSON exhausts the parser's stack; treat it
            # as a bad request rather than letting it surface as a 500.
            raise OtlpDecodeError("JSON body nesting too deep") from exc
        _normalise_hex_ids(payload)
        try:
            json_format.ParseDict(payload, request)
        except json_format.ParseError as exc:
            raise OtlpDecodeError(f"invalid OTLP JSON: {exc}") from exc
        return request

    raise OtlpDecodeError(f"unsupported content type: {content_type!r}")


def request_to_span_records(request: ExportTraceServiceRequest) -> list[SpanRecord]:
    """Flatten an OTLP request into one ``SpanRecord`` per span."""
    records: list[SpanRecord] = []
    for resource_spans in request.resource_spans:
        resource_attrs = _key_values_to_dict(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            scope_attrs = _key_values_to_dict(scope_spans.scope.attributes)
            for span in scope_spans.spans:
                merged = {**resource_attrs, **scope_attrs}
                merged.update(_key_values_to_dict(span.attributes))
                records.append(_span_to_record(span, merged))
    return records


def _span_to_record(span: Any, attributes: dict[str, Any]) -> SpanRecord:
    parent = span.parent_span_id.hex() if span.parent_span_id else None
    start = _nanos_to_dt(span.start_time_unix_nano)
    end = _nanos_to_dt(span.end_time_unix_nano)
    duration_ms = None
    if span.start_time_unix_nano and span.end_time_unix_nano:
        duration_ms = (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000

    run_cost = attributes.get(semconv.ARGOX_RUN_COST)
    if run_cost is None:
        run_cost = attributes.get(semconv.GEN_AI_USAGE_COST)

    return SpanRecord(
        trace_id=span.trace_id.hex(),
        span_id=span.span_id.hex(),
        parent_span_id=parent,
        name=span.name or None,
        start_time=start,
        end_time=end,
        duration_ms=duration_ms,
        agent_name=attributes.get(semconv.ARGOX_AGENT_NAME)
        or attributes.get(semconv.SERVICE_NAME),
        agent_version=attributes.get(semconv.ARGOX_AGENT_VERSION),
        policy_decision=attributes.get(semconv.ARGOX_POLICY_DECISION),
        run_cost=_as_float(run_cost),
        run_success=_as_bool(attributes.get(semconv.ARGOX_RUN_SUCCESS)),
        attributes=attributes,
    )


def _nanos_to_dt(nanos: int) -> Optional[datetime]:
    if not nanos:
        return None
    return datetime.fromtimestamp(nanos / 1_000_000_000, tz=timezone.utc)


def _as_float(value: Any) -> Optional[float]:
    """Coerce an OTLP attribute into a finite ``float``.

    OTLP doubles (and strings such as ``"nan"``) can carry NaN/Infinity,
    which would poison every index aggregate they enter and cannot be
    encoded in the JSON metrics responses, so non-finite values degrade to
    ``None``.
    """
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_bool(value: Any) -> Optional[bool]:
    """Coerce an OTLP attribute into a ``bool`` for the DuckDB BOOLEAN column.

    SDKs sometimes encode ``run.success`` as a string or number rather than a
    native bool. Returning the raw value would make the whole batch's
    ``executemany`` fail on a type mismatch, so unrecognised values degrade to
    ``None`` instead.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"true", "1", "yes"}:
            return True
        if normalised in {"false", "0", "no"}:
            return False
    return None


def _key_values_to_dict(key_values: Any) -> dict[str, Any]:
    return {kv.key: _anyvalue_to_py(kv.value) for kv in key_values}


def _anyvalue_to_py(value: AnyValue) -> Any:
    """Convert an OTLP ``AnyValue`` into a JSON-serialisable Python value."""
    which = value.WhichOneof("value")
    if which == "string_value":
        return value.string_value
    if which == "bool_value":
        return value.bool_value
    if which == "int_value":
        return value.int_value
    if which == "double_value":
        return value.double_value
    if which == "bytes_value":
        # bytes are not JSON-serialisable; encode as lowercase hex.
        return value.bytes_value.hex()
    if which == "array_value":
        return [_anyvalue_to_py(item) for item in value.array_value.values]
    if which == "kvlist_value":
        return {
            kv.key: _anyvalue_to_py(kv.value) for kv in value.kvlist_value.values
        }
    return None


def _normalise_hex_ids(payload: Any) -> None:
    """Rewrite hex-encoded OTLP id fields to base64 in-place for protobuf JSON.

    Strict OTLP/JSON emits ``traceId``/``spanId``/``parentSpanId`` as hex,
    while ``json_format`` expects base64 for ``bytes`` fields. Values that are
    not valid hex (e.g. already base64) are left untouched.

    Implemented iteratively with an explicit stack so deeply nested payloads
    cannot exhaust the interpreter's recursion limit.
    """
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, val in node.items():
                if key in _HEX_ID_FIELDS and isinstance(val, str):
                    node[key] = _hex_to_b64(val)
                elif isinstance(val, (dict, list)):
                    stack.append(val)
        elif isinstance(node, list):
            stack.extend(node)


def _hex_to_b64(value: str) -> str:
    # KNOWN LIMITATION: a base64 id that happens to be all hex chars and of
    # even length (e.g. "abcdef01") is indistinguishable from hex here and gets
    # misconverted. Low impact because protobuf is the primary, lossless
    # transport and JSON is documented as best-effort; revisit if a strict
    # OTLP/JSON client surfaces id corruption.
    if len(value) % 2 != 0 or not _HEX_RE.match(value):
        return value
    try:
        return base64.b64encode(binascii.unhexlify(value)).decode("ascii")
    except (binascii.Error, ValueError):
        return value
