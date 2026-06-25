# Argox Exporter Development Guide

This guide provides a comprehensive technical overview for developers who want to write custom exporters for the Argox SDK. It details the two distinct types of exporters in the Argox ecosystem, their lifecycles, fault-tolerance requirements, registration methods, and testing strategies, along with complete reference implementations.

---

## 1. Understanding the Two Exporter Types in Argox

Argox makes a strict architectural distinction between two types of exporters. Choosing the correct one depends on the granularity and structure of the data you need to ship:

| Feature | Argox Run Exporter (`ExporterBase`) | OpenTelemetry Span Exporter (`SpanExporter`) |
|---|---|---|
| **Data Received** | A single `AgentRunMetrics` object. | A sequence of OTel `ReadableSpan` objects. |
| **Granularity** | **Run-level summary** (aggregated tokens, total cost, list of tools called, phase timings, success status, final output, and prompt). | **Span-level telemetry** (fine-grained trace waterfalls, individual tool execution durations, step-by-step OTel events). |
| **Execution** | Runs synchronously in the `finally` block of the `ArgoxManager` run lifecycle. | Runs asynchronously via the OTel trace pipeline (batched or simple). |
| **Scope** | Configured **per-run** via the `@argox.monitor` decorator or `ArgoxManager`. | Configured **globally** at startup via `init_telemetry()`. |
| **Primary Use** | Structured database indexes, audit logs, and dashboard run records. | Real-time tracing backends (Argox Collector, Jaeger, Zipkin, Azure Blob Storage). |

---

## 2. Part 1: Writing an Argox Run Exporter (`ExporterBase`)

An Argox Run Exporter is used to ship the overall execution summary of a single agent run once it is fully completed.

### The Contract
To implement a run exporter, you must subclass `ExporterBase` (defined in `argox.interfaces.exporter.py`) and implement the `export` method:

```python
from abc import ABC, abstractmethod
from argox.core.state import AgentRunMetrics

class ExporterBase(ABC):

    @abstractmethod
    def export(self, metrics: AgentRunMetrics) -> None:
        """
        Persists or sends the metrics from a run to their destination.
        """
        pass
```

### Critical Requirements & Best Practices

1. **Read-Only Metrics**: The `metrics` object passed to `export` is fully populated and should be treated as **read-only**. Do not modify any fields of `metrics`, with the sole exception of appending diagnostic errors to `metrics.exporter_errors` if the export fails.
2. **Strict Fault Tolerance (Never Crash the Run)**: An exporter must **never** propagate exceptions back to the caller. If the export destination is down (e.g., network timeout, database lock), the exporter must catch all exceptions, log them, append the error description to `metrics.exporter_errors`, and return gracefully. The `ArgoxManager` catches any unhandled exporter exceptions as a safety net, but well-behaved exporters should handle their own errors.

### Example: A Custom Webhook Exporter
Here is a conceptual example of a run exporter that posts a JSON summary to an external webhook:

```python
import urllib.request
import json
import logging
from argox.interfaces.exporter import ExporterBase
from argox.core.state import AgentRunMetrics

logger = logging.getLogger(__name__)

class WebhookRunExporter(ExporterBase):
    def __init__(self, endpoint_url: str):
        self._url = endpoint_url

    def export(self, metrics: AgentRunMetrics) -> None:
        # 1. Serialize metrics to a dictionary
        payload = {
            "run_id": metrics.run_id,
            "agent_name": metrics.agent_name,
            "success": metrics.success,
            "tokens": {
                "input": sum(c.input_tokens for c in metrics.api_calls),
                "output": sum(c.output_tokens for c in metrics.api_calls),
            },
            "tools_called": metrics.tools_called,
            "start_time": metrics.start_time.isoformat() if metrics.start_time else None,
            "end_time": metrics.end_time.isoformat() if metrics.end_time else None,
        }

        # 2. Send the payload with strict error handling
        try:
            req = urllib.request.Request(
                self._url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP error status: {response.status}")
        except Exception as e:
            error_msg = f"Failed to export run {metrics.run_id} to webhook: {e}"
            logger.error(error_msg)
            # Record the error in the metrics object
            metrics.exporter_errors.append(error_msg)
```

---

## 3. Part 2: Writing an OTel Span Exporter (`SpanExporter`)

If you want to export raw, fine-grained traces (e.g., individual tool child spans, parent agent spans, OTel events), you must write a standard OpenTelemetry `SpanExporter`.

### The Contract
You must subclass `opentelemetry.sdk.trace.export.SpanExporter` and implement its interface:

```python
from collections.abc import Sequence
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

class CustomSpanExporter(SpanExporter):

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """
        Exports a batch of spans. Returns SpanExportResult.SUCCESS or FAILURE.
        """
        pass

    def shutdown(self) -> None:
        """
        Cleans up resources (e.g. closing sockets, clients).
        """
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """
        Flushes any buffered spans.
        """
        return True
```

### Key Considerations for Span Exporters
* **Asynchronous Batching**: In production, it is highly recommended to pair your custom exporter with OTel's `BatchSpanProcessor` to avoid blocking the hot execution path of the agent.
* **GenAI Semantic Conventions**: Your exporter will receive spans containing GenAI attributes (e.g., `gen_ai.request.model`, `gen_ai.operation.name`). You should ensure your storage/index system can query these conventions (as the Argox Collector does with DuckDB).
* **PII Awareness**: Spans exported via this pipeline may contain sensitive data unless redacted by in-flight `ArgoxProcessor` middleware. Be mindful of where the spans are shipped.

---

## 4. Packaging, Registration, and Distribution

### Packaging Naming Convention
Custom exporters should be packaged as standalone, installable Python packages using the naming convention:
* `argox-exporter-<destination>` (e.g., `argox-exporter-prometheus`, `argox-exporter-slack`).

### Registration

#### A. Registering a Run Exporter (`ExporterBase`)
Users register your run exporter on a per-run basis by passing it to the `@argox.monitor` decorator:

```python
from argox_webhook import WebhookRunExporter

@argox.monitor(
    agent=my_agent,
    exporters=[WebhookRunExporter("https://api.mycompany.com/audit-webhook")]
)
async def run_my_agent(prompt: str):
    ...
```

#### B. Registering a Span Exporter (`SpanExporter`)
Users register your span exporter globally at application startup using Argox's `init_telemetry` helper:

```python
from argox.core import init_telemetry
from argox_custom_span import CustomSpanExporter

init_telemetry(exporters=[CustomSpanExporter(connection_string="...")])
```

---

## 5. Testing Your Exporters

### Testing Run Exporters
1. **Mock the Destination**: Mock network requests or database connections using `unittest.mock`.
2. **Verify Data Serialization**: Ensure all necessary run metrics (tokens, tool lists, status) are serialized correctly.
3. **Verify Fault Tolerance**: Write a test where the mock destination raises an exception (e.g., `TimeoutError`). Assert that:
   - The `export()` method does **not** raise an exception.
   - The error message is appended to `metrics.exporter_errors`.

### Testing Span Exporters
1. **Simulate Spans**: Use `opentelemetry.sdk.trace.ReadableSpan` or mock spans.
2. **Verify Output Format**: Ensure spans are formatted correctly (e.g., proper JSON/JSONL representation).
3. **Verify Return Status**: Ensure `export()` returns `SpanExportResult.SUCCESS` on success and `SpanExportResult.FAILURE` on error.

---

## 6. Complete Reference Implementation

Below is a complete, self-contained reference implementation of a custom webhook run exporter, a local JSONL span exporter, and a comprehensive test suite.

### A. The Webhook Run Exporter (`webhook_exporter.py`)
```python
# webhook_exporter.py
import urllib.request
import json
import logging
from argox.interfaces.exporter import ExporterBase
from argox.core.state import AgentRunMetrics

logger = logging.getLogger(__name__)

class WebhookRunExporter(ExporterBase):
    """A custom Run Exporter that posts a lightweight run summary to a webhook."""
    
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def export(self, metrics: AgentRunMetrics) -> None:
        summary = {
            "run_id": metrics.run_id,
            "agent_name": metrics.agent_name,
            "success": metrics.success,
            "total_tokens": sum(call.total_tokens for call in metrics.api_calls),
            "tools_called": metrics.tools_called,
            "error_count": len(metrics.exporter_errors)
        }

        try:
            data = json.dumps(summary).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            # 2-second timeout to avoid hanging the agent run
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP status code: {response.status}")
        except Exception as e:
            error_msg = f"WebhookRunExporter failed to post to {self.endpoint}: {e}"
            logger.error(error_msg)
            # Append diagnostic message to metrics; do not re-raise!
            metrics.exporter_errors.append(error_msg)
```

### B. The Local JSONL Span Exporter (`jsonl_span_exporter.py`)
```python
# jsonl_span_exporter.py
from collections.abc import Sequence
import logging
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)

class LocalJsonlSpanExporter(SpanExporter):
    """A custom OTel Span Exporter that appends span JSON records to a local file."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._shutdown = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._shutdown:
            return SpanExportResult.FAILURE
        
        if not spans:
            return SpanExportResult.SUCCESS

        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                for span in spans:
                    # Write span as a single-line JSON record
                    f.write(span.to_json(indent=None) + "\n")
            return SpanExportResult.SUCCESS
        except Exception as e:
            logger.exception("LocalJsonlSpanExporter failed to write spans: %s", e)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._shutdown = True

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
```

### C. The Test Suite (`test_exporters.py`)
```python
# test_exporters.py
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult

from argox.core.state import AgentRunMetrics, ApiCallRecord
from .webhook_exporter import WebhookRunExporter
from .jsonl_span_exporter import LocalJsonlSpanExporter

# =====================================================================
# 1. Tests for WebhookRunExporter (ExporterBase)
# =====================================================================

@pytest.fixture
def mock_metrics():
    metrics = AgentRunMetrics(run_id="run-123")
    metrics.agent_name = "test-agent"
    metrics.success = True
    metrics.tools_called = ["get_weather", "search"]
    metrics.api_calls = [
        ApiCallRecord(call_number=1, input_tokens=10, output_tokens=20, total_tokens=30),
        ApiCallRecord(call_number=2, input_tokens=5, output_tokens=15, total_tokens=20),
    ]
    return metrics

def test_webhook_exporter_success(mock_metrics):
    exporter = WebhookRunExporter("http://mock-webhook.local")
    
    # Mock urllib.request.urlopen
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        exporter.export(mock_metrics)

        # Assertions
        mock_urlopen.assert_called_once()
        assert len(mock_metrics.exporter_errors) == 0

def test_webhook_exporter_fault_tolerance(mock_metrics):
    exporter = WebhookRunExporter("http://mock-webhook.local")
    
    # Mock urlopen to raise a network timeout error
    with patch("urllib.request.urlopen", side_effect=OSError("Connection timed out")):
        # Ensure it does NOT raise an exception
        exporter.export(mock_metrics)

        # Assertions
        assert len(mock_metrics.exporter_errors) == 1
        assert "Connection timed out" in mock_metrics.exporter_errors[0]


# =====================================================================
# 2. Tests for LocalJsonlSpanExporter (SpanExporter)
# =====================================================================

def test_jsonl_span_exporter_success(tmp_path):
    output_file = tmp_path / "spans.jsonl"
    exporter = LocalJsonlSpanExporter(str(output_file))

    # Mock ReadableSpans
    span_mock1 = MagicMock(spec=ReadableSpan)
    span_mock1.to_json.return_value = '{"name": "span-1"}'
    
    span_mock2 = MagicMock(spec=ReadableSpan)
    span_mock2.to_json.return_value = '{"name": "span-2"}'

    # Export spans
    result = exporter.export([span_mock1, span_mock2])

    assert result == SpanExportResult.SUCCESS
    
    # Verify file contents
    assert os.path.exists(output_file)
    with open(output_file, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"name": "span-1"}
    assert json.loads(lines[1]) == {"name": "span-2"}

def test_jsonl_span_exporter_failure(tmp_path):
    # Pass an invalid/unwritable directory to force an exception
    exporter = LocalJsonlSpanExporter(str(tmp_path))

    span_mock = MagicMock(spec=ReadableSpan)
    span_mock.to_json.return_value = '{"name": "span"}'

    # Export must return FAILURE rather than crashing the app
    result = exporter.export([span_mock])
    assert result == SpanExportResult.FAILURE
```
