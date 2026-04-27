"""
IFACE-03 — PolicyClient
========================
Contrato que abstrae la comunicación con el servicio externo de políticas.

Desacopla el SDK del transporte concreto: el stub local (para desarrollo sin
red) y el cliente SSE real (para producción) son implementaciones distintas
del mismo contrato. El ArgoxManager solo conoce esta interfaz.

Modelo de evaluación
--------------------
Toda evaluación devuelve un ``PolicyResult``: un objeto inmutable con el
veredicto (``passed``), un motivo legible (``reason``) y el nombre de la
regla que lo generó (``rule_id``). Esto permite al Manager loguear y auditar
sin depender del formato interno de cada implementación.

Puntos de evaluación
--------------------
El ciclo de vida de una ejecución tiene tres puntos donde se aplican políticas:

  1. ``check_input``  — antes de enviar el prompt al agente.
  2. ``is_tool_allowed``   — antes de permitir que el agente llame a una tool.
  3. ``check_output`` — después de recibir la respuesta final del agente.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyResult:
    """
    Resultado inmutable de una evaluación de política.

    Attributes:
        passed:  ``True`` si la evaluación no encontró violaciones.
        reason:  Descripción legible del motivo del veredicto.
                 Vacío cuando ``passed`` es ``True``.
        rule_id: Identificador de la regla que generó el veredicto.
                 Útil para correlacionar con el servicio externo de políticas.
                 Vacío cuando ``passed`` es ``True``.
    """
    passed: bool
    reason: str = ""
    rule_id: str = ""

    # Constructores semánticos para mayor legibilidad en las implementaciones.

    @classmethod
    def ok(cls) -> "PolicyResult":
        """Veredicto positivo sin información adicional."""
        return cls(passed=True)

    @classmethod
    def block(cls, reason: str, rule_id: str = "") -> "PolicyResult":
        """Veredicto negativo con motivo obligatorio."""
        return cls(passed=False, reason=reason, rule_id=rule_id)


class PolicyClient(ABC):
    """
    Interfaz abstracta para clientes del servicio de políticas.

    Implementaciones previstas:
        - ``LocalPolicyClient``  — reglas hardcodeadas, sin red. Stub de desarrollo.
        - ``SsePolicyClient``    — consume el servicio externo vía SSE con caché local.

    Todas las implementaciones deben:
        - Ser seguras ante fallos de red: si el servicio no responde, aplicar
          la política de fallback configurada (por defecto: permitir con warning).
        - No lanzar excepciones hacia el Manager — capturar y devolver
          ``PolicyResult.block(reason="...")`` si algo falla internamente.
        - Ser stateless por llamada: el estado de caché es interno a la implementación.

    Ejemplo de uso en ArgoxManager::

        result = await self.policy.check_input(prompt)
        if not result.passed:
            metrics.policy_violations.append(result.reason)
            raise PermissionError(f"[POLICY:{result.rule_id}] {result.reason}")
    """

    @abstractmethod
    async def check_input(self, text: str) -> PolicyResult:
        """
        Evalúa el prompt del usuario antes de enviarlo al agente.

        Args:
            text: El prompt completo tal como lo introduce el usuario.

        Returns:
            ``PolicyResult.ok()`` si el input es aceptable.
            ``PolicyResult.block(...)`` si debe bloquearse la ejecución.
        """
        ...

    @abstractmethod
    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        """
        Determina si una tool puede ser expuesta al agente.
        Se evalúa en pre-flight: el Manager filtra la lista ANTES
        de que el agente la reciba.

        Args:
            tool_name: Nombre de la tool tal como está registrada en el agente.

        Returns:
            ``PolicyResult.ok()`` si la tool puede ejecutarse.
            ``PolicyResult.block(...)`` si debe deshabilitarse.
        """
        ...

    @abstractmethod
    async def check_output(self, text: str) -> PolicyResult:
        """
        Evalúa la respuesta final del agente antes de devolverla al usuario.

        Args:
            text: El output final del agente como string puro.

        Returns:
            ``PolicyResult.ok()`` si el output es aceptable.
            ``PolicyResult.block(...)`` si debe marcarse como violación.
        """
        ...
