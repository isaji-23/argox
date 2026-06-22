from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from argox.core.state import AgentRunMetrics
from argox.exporters.http_run import HttpRunExporter


@pytest.fixture
def metrics() -> AgentRunMetrics:
    metrics_obj = AgentRunMetrics(agent_name="test-agent")
    metrics_obj.run_id = "run-test-id"
    metrics_obj.final_output = "hello world"
    metrics_obj.success = True
    return metrics_obj


@pytest.fixture
def mock_sleep():
    with patch("time.sleep") as mock:
        yield mock


def test_exporter_happy_path_202(metrics):
    exporter = HttpRunExporter(endpoint="http://localhost:8000")

    with patch.object(exporter._client, "post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 202
        mock_post.return_value = mock_response

        exporter.export(metrics)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://localhost:8000/v1/runs"
        assert kwargs["json"] == metrics.to_dict()
        assert len(metrics.exporter_errors) == 0


def test_exporter_happy_path_200_durable(metrics):
    exporter = HttpRunExporter(
        endpoint="http://localhost:8000/",
        api_key="secret-key",
        durable=True,
    )

    # Check client headers initialized properly
    assert exporter._client.headers["Authorization"] == "Bearer secret-key"
    assert exporter._client.headers["X-Argox-Durable"] == "true"

    with patch.object(exporter._client, "post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        exporter.export(metrics)

        mock_post.assert_called_once()
        assert len(metrics.exporter_errors) == 0


def test_exporter_5xx_retry_and_success(metrics, mock_sleep):
    exporter = HttpRunExporter(endpoint="http://localhost:8000", max_retries=2)

    with patch.object(exporter._client, "post") as mock_post:
        resp_500 = MagicMock(spec=httpx.Response)
        resp_500.status_code = 500
        resp_500.text = "Internal Server Error"

        resp_202 = MagicMock(spec=httpx.Response)
        resp_202.status_code = 202

        # Fail twice, succeed on third attempt
        mock_post.side_effect = [resp_500, resp_500, resp_202]

        exporter.export(metrics)

        assert mock_post.call_count == 3
        # Should backoff: attempt 1 (no sleep), attempt 2 (sleep 0.5s), attempt 3 (sleep 1.0s)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)
        assert len(metrics.exporter_errors) == 0


def test_exporter_network_error_retry_and_success(metrics, mock_sleep):
    exporter = HttpRunExporter(endpoint="http://localhost:8000", max_retries=3)

    with patch.object(exporter._client, "post") as mock_post:
        resp_202 = MagicMock(spec=httpx.Response)
        resp_202.status_code = 202

        # Raise connection error twice, then succeed
        mock_post.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.ConnectError("Connection refused"),
            resp_202,
        ]

        exporter.export(metrics)

        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2
        assert len(metrics.exporter_errors) == 0


def test_exporter_exhaustion_5xx(metrics, mock_sleep):
    exporter = HttpRunExporter(endpoint="http://localhost:8000", max_retries=3)

    with patch.object(exporter._client, "post") as mock_post:
        resp_500 = MagicMock(spec=httpx.Response)
        resp_500.status_code = 500
        resp_500.text = "Internal Error"
        mock_post.return_value = resp_500

        exporter.export(metrics)

        # 1 initial + 3 retries = 4 attempts total
        assert mock_post.call_count == 4
        assert mock_sleep.call_count == 3
        assert len(metrics.exporter_errors) == 1
        assert "HttpRunExporter: Failed to export after 4 attempts." in metrics.exporter_errors[0]
        assert "HTTP 500" in metrics.exporter_errors[0]


def test_exporter_exhaustion_network_errors(metrics, mock_sleep):
    exporter = HttpRunExporter(endpoint="http://localhost:8000", max_retries=2)

    with patch.object(exporter._client, "post") as mock_post:
        mock_post.side_effect = httpx.ConnectTimeout("Timeout connecting")

        exporter.export(metrics)

        # 1 initial + 2 retries = 3 attempts total
        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2
        assert len(metrics.exporter_errors) == 1
        assert "HttpRunExporter: Failed to export after 3 attempts." in metrics.exporter_errors[0]
        assert "ConnectTimeout" in metrics.exporter_errors[0]


def test_exporter_non_retriable_error_4xx(metrics, mock_sleep):
    exporter = HttpRunExporter(endpoint="http://localhost:8000", max_retries=3)

    with patch.object(exporter._client, "post") as mock_post:
        resp_400 = MagicMock(spec=httpx.Response)
        resp_400.status_code = 400
        resp_400.text = "Bad Request"
        mock_post.return_value = resp_400

        exporter.export(metrics)

        # Non-retriable 400 must stop immediately and not retry
        mock_post.assert_called_once()
        mock_sleep.assert_not_called()
        assert len(metrics.exporter_errors) == 1
        assert "HttpRunExporter: HTTP 400: Bad Request" in metrics.exporter_errors[0]


def test_exporter_unexpected_exception_never_propagates(metrics, mock_sleep):
    exporter = HttpRunExporter(endpoint="http://localhost:8000", max_retries=1)

    with patch.object(exporter._client, "post") as mock_post:
        mock_post.side_effect = RuntimeError("Critical memory corruption")

        # This should never propagate
        try:
            exporter.export(metrics)
        except Exception as exc:
            pytest.fail(f"Exporter raised exception: {exc}")

        # 1 initial + 1 retry = 2 attempts total
        assert mock_post.call_count == 2
        assert len(metrics.exporter_errors) == 1
        assert "HttpRunExporter: Failed to export after 2 attempts." in metrics.exporter_errors[0]
        assert "RuntimeError" in metrics.exporter_errors[0]
