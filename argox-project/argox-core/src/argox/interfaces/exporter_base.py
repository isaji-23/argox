"""
IFACE-02 — ExporterBase
=======================
Contrato que debe implementar todo exportador de métricas.

Un exportador recibe un AgentRunMetrics ya completo (la ejecución ha terminado)
y lo envía a un destino: fichero local, blob storage, sistema de observabilidad…

La comunidad puede implementar exportadores custom instalándolos como paquetes
independientes y registrándolos en el ArgoxManager.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from argox.core.state import AgentRunMetrics


class ExporterBase(ABC):
    """
    Interfaz abstracta para exportadores de métricas.

    Cada exportador implementa un único método (``export``) que recibe las
    métricas de una ejecución y las persiste o envía a su destino.

    Exportadores oficiales incluidos en argox-core:
        - ``JsonlExporter``   — persiste en fichero ``.jsonl`` local.
        - ``ConsoleExporter`` — imprime resumen legible por pantalla.
        - ``AzureBlobExporter`` — sube a Azure Blob Storage.

    Ejemplo de exportador custom para Prometheus::

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
        Persiste o envía las métricas de una ejecución a su destino.

        Este método se llama una vez por ejecución, tras aplicar las políticas
        de output y marcar el resultado como éxito o fallo. En este punto
        ``metrics`` está completamente poblado.

        Args:
            metrics: Métricas completas de la ejecución. Solo lectura —
                     el exportador no debe modificar este objeto.

        Note:
            Las implementaciones deben ser tolerantes a fallos: si el destino
            no está disponible (red caída, cuota superada…), se recomienda
            registrar el error en logging y no relanzar la excepción, para
            no interrumpir el flujo principal del agente.
        """
        ...
