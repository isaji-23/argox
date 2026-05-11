import json
from pathlib import Path

from argox.exporters.jsonl import JsonlSpanExporter
from opentelemetry.sdk.trace.export import SpanExportResult


class MockReadableSpan:
    def __init__(self, name="test_span", data_dict=None):
        self.name = name
        self.data_dict = data_dict or {
            "name": name,
            "context": {"trace_id": "0x123", "span_id": "0x456"},
        }

    def to_json(self):
        return json.dumps(self.data_dict)


def test_jsonl_span_exporter_exports_spans(tmp_path: Path):
    file_path = tmp_path / "spans.jsonl"
    exporter = JsonlSpanExporter(file_path)

    spans = [MockReadableSpan(name="span1"), MockReadableSpan(name="span2")]

    result = exporter.export(spans)

    assert result == SpanExportResult.SUCCESS
    assert file_path.exists()

    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    span1_data = json.loads(lines[0])
    span2_data = json.loads(lines[1])

    assert span1_data["name"] == "span1"
    assert span2_data["name"] == "span2"


def test_jsonl_span_exporter_creates_directory(tmp_path: Path):
    file_path = tmp_path / "nested" / "dir" / "spans.jsonl"
    exporter = JsonlSpanExporter(file_path)

    assert file_path.parent.exists()

    spans = [MockReadableSpan()]
    exporter.export(spans)

    assert file_path.exists()


def test_jsonl_span_exporter_force_flush_and_shutdown():
    exporter = JsonlSpanExporter("dummy.jsonl")
    assert exporter.force_flush() is True
    # shutdown shouldn't raise any exception
    exporter.shutdown()
