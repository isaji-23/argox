"""Semantic-convention attribute keys recognised by the Collector.

These constants mirror the SDK-side definitions in
``argox-core/src/argox/semconv/attributes.py`` and the relevant subset of the
OpenTelemetry GenAI semantic conventions. They are duplicated here (rather than
imported) so the Collector stays independently deployable without a runtime
dependency on ``argox-core``.
"""

from __future__ import annotations

from typing import Final

# Argox span attributes promoted into dedicated SpanRecord columns.
ARGOX_AGENT_NAME: Final[str] = "argox.agent.name"
ARGOX_AGENT_VERSION: Final[str] = "argox.agent.version"
ARGOX_POLICY_DECISION: Final[str] = "argox.policy.decision"
ARGOX_RUN_SUCCESS: Final[str] = "argox.run.success"
ARGOX_RUN_COST: Final[str] = "argox.run.cost"

# OpenTelemetry GenAI semantic conventions used for cost enrichment.
GEN_AI_REQUEST_MODEL: Final[str] = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL: Final[str] = "gen_ai.response.model"
GEN_AI_USAGE_INPUT_TOKENS: Final[str] = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final[str] = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_COST: Final[str] = "gen_ai.usage.cost"

# Standard OTel resource attribute carrying the logical service name.
SERVICE_NAME: Final[str] = "service.name"

# Attribute the Collector sets when its residual PII scan finds a match.
ARGOX_PII_RESIDUAL_DETECTED: Final[str] = "argox.pii.residual_detected"
