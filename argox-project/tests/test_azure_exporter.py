"""Tests for the AzureBlobSpanExporter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from azure.core.exceptions import AzureError
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult

from argox_azure import AzureBlobSpanExporter


def test_exporter_success():
    with patch("argox_azure.exporter.BlobServiceClient") as MockClient:
        mock_client_instance = MockClient.from_connection_string.return_value
        mock_blob_client = mock_client_instance.get_blob_client.return_value

        exporter = AzureBlobSpanExporter(
            connection_string="DefaultEndpointsProtocol=http;AccountName=dev;AccountKey=key;BlobEndpoint=http://127.0.0.1:10000/dev;",
            container_name="test-container",
            prefix="custom-spans",
        )

        provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
        processor = SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("test_span") as span:
            span.set_attribute("test_attr", "value")

        # SimpleSpanProcessor exports synchronously on span end
        mock_client_instance.get_blob_client.assert_called_once()
        kwargs = mock_client_instance.get_blob_client.call_args.kwargs
        assert kwargs["container"] == "test-container"
        assert kwargs["blob"].startswith("custom-spans/")
        assert kwargs["blob"].endswith(".jsonl")

        mock_blob_client.upload_blob.assert_called_once()
        uploaded_data = mock_blob_client.upload_blob.call_args[0][0].decode("utf-8")

        # Verify it's a valid JSONL with our span
        lines = [line for line in uploaded_data.split("\n") if line.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["name"] == "test_span"
        assert data["attributes"]["test_attr"] == "value"


def test_exporter_empty_batch():
    with patch("argox_azure.exporter.BlobServiceClient") as MockClient:
        mock_client_instance = MockClient.from_connection_string.return_value
        mock_blob_client = mock_client_instance.get_blob_client.return_value

        exporter = AzureBlobSpanExporter(
            connection_string="fake_conn_str",
            container_name="test",
        )
        
        result = exporter.export([])
        
        assert result == SpanExportResult.SUCCESS
        mock_blob_client.upload_blob.assert_not_called()


def test_exporter_azure_error():
    with patch("argox_azure.exporter.BlobServiceClient") as MockClient:
        mock_client_instance = MockClient.from_connection_string.return_value
        mock_blob_client = mock_client_instance.get_blob_client.return_value
        mock_blob_client.upload_blob.side_effect = AzureError("Auth failed")

        exporter = AzureBlobSpanExporter(
            connection_string="fake_conn_str",
            container_name="test",
        )

        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        
        # Create a real readable span to pass to export directly
        with tracer.start_as_current_span("test") as span:
            pass
            
        # span is instance of _Span, which is ReadableSpan
        result = exporter.export([span])
        
        assert result == SpanExportResult.FAILURE


def test_exporter_initialization_failure():
    with patch("argox_azure.exporter.BlobServiceClient") as MockClient:
        MockClient.from_connection_string.side_effect = ValueError("Invalid connection string")

        exporter = AzureBlobSpanExporter(
            connection_string="bad_conn_str",
            container_name="test",
        )
        
        # It shouldn't crash, but just log the error and set client to None
        assert exporter._blob_service_client is None
        
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("test") as span:
            pass
            
        result = exporter.export([span])
        assert result == SpanExportResult.FAILURE
