"""
IFACE-02 — Exporter
=======================
Contract that every metrics exporter must implement.

An exporter receives a fully populated AgentRunMetrics (the run has finished)
and sends it to a destination: local file, blob storage, observability system

The community can implement custom exporters by installing them as standalone
packages and registering them with the ArgoxManager.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from argox.core.state import AgentRunMetrics

class ExporterBase(ABC):
    """
    Abstract interface for metrics exporters.

    Each exporter implements a single method (``export``) that receives the
    metrics from a run and persists or sends them to their destination.

    Official exporters included in argox-core:
        - ``JsonlExporter``   — persists to a local ``.jsonl`` file.
        - ``ConsoleExporter`` — prints a human-readable summary to stdout.
        - ``AzureBlobExporter`` — uploads to Azure Blob Storage.
    
    Example of a custom exporter for Prometheus::
        class PrometheusExporter(ExporterBase):
            def __init__(self, push_gateway_url: str):
                self._url = push_gateway_url
            def export(self, metrics: AgentRunMetrics) -> None:
                push_to_gateway(
                    self._url,
                    job=metrics.agent_name,
                    registry=build_registry(metrics),
                )
    """
    
    @abstractmethod
    def export(self, metrics: AgentRunMetrics) -> None:
        """
        Persists or sends the metrics from a run to their destination.
        This method is called once per run, after applying output policies
        and marking the result as success or failure. At this point
        ``metrics`` is fully populated.
        Args:
            metrics: Complete metrics for the run. Read-only —
                     the exporter must not modify this object.
        Note:
            Implementations should be fault-tolerant: if the destination
            is unavailable (network down, quota exceeded…), it is recommended
            to log the error and not re-raise the exception, so as not to
            interrupt the agent's main flow.
        """
        ...