"""Tests for the JsonlSpanExporter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult

from argox.observability import JsonlSpanExporter


def _make_tracer(exporter: JsonlSpanExporter):
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test")


def test_jsonl_span_exporter_exports_spans(tmp_path: Path):
    file_path = tmp_path / "spans.jsonl"
    exporter = JsonlSpanExporter(file_path)
    tracer = _make_tracer(exporter)

    with tracer.start_as_current_span("span1"):
        pass
    with tracer.start_as_current_span("span2"):
        pass

    exporter.shutdown()

    assert file_path.exists()
    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    span1_data = json.loads(lines[0])
    span2_data = json.loads(lines[1])

    # OTel JSON output includes many fields, we just check names
    assert span1_data["name"] == "span1"
    assert span2_data["name"] == "span2"


def test_jsonl_span_exporter_appends_spans(tmp_path: Path):
    file_path = tmp_path / "append.jsonl"
    exporter = JsonlSpanExporter(file_path)
    tracer = _make_tracer(exporter)

    with tracer.start_as_current_span("batch1"):
        pass
    exporter.force_flush()

    with tracer.start_as_current_span("batch2"):
        pass
    exporter.shutdown()

    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "batch1"
    assert json.loads(lines[1])["name"] == "batch2"


def test_jsonl_span_exporter_creates_directory(tmp_path: Path):
    file_path = tmp_path / "nested" / "dir" / "spans.jsonl"
    exporter = JsonlSpanExporter(file_path)
    assert file_path.parent.exists()
    exporter.shutdown()


def test_jsonl_span_exporter_force_flush_and_shutdown(tmp_path: Path):
    file_path = tmp_path / "flush.jsonl"
    exporter = JsonlSpanExporter(file_path)
    assert exporter.force_flush() is True
    exporter.shutdown()
    assert exporter._fh.closed


def test_jsonl_span_exporter_error_handling(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    file_path = tmp_path / "error.jsonl"
    exporter = JsonlSpanExporter(file_path)

    # Mock the file handle's write method to raise an error
    exporter._fh.write = MagicMock(side_effect=OSError("Disk full"))

    mock_span = MagicMock()
    mock_span.to_json.return_value = '{"name": "test"}'

    result = exporter.export([mock_span])

    assert result == SpanExportResult.FAILURE
    assert "Failed to export spans" in caplog.text
    assert "Disk full" in caplog.text

    exporter.shutdown()


def test_jsonl_span_exporter_failure_after_shutdown(tmp_path: Path):
    file_path = tmp_path / "after_shutdown.jsonl"
    exporter = JsonlSpanExporter(file_path)
    exporter.shutdown()

    result = exporter.export([MagicMock()])
    assert result == SpanExportResult.FAILURE
