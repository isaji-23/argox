"""Normalise GenAI semantic-convention attribute variants.

Different instrumentation libraries emit token usage and model identity under
slightly different keys: pre-1.27 OTel GenAI used ``gen_ai.usage.prompt_tokens``
and ``gen_ai.usage.completion_tokens``, while OpenInference instrumentation uses
``llm.model_name`` and ``llm.token_count.*``. This stage copies the first
variant found onto the canonical key so the downstream cost stage only has to
read one shape. Variant keys are left in place to preserve the span as
received.
"""

from __future__ import annotations

import dataclasses

from argox_collector import semconv
from argox_collector.index.base import SpanRecord

# Canonical key -> variant keys checked in priority order. A canonical key
# already present always wins, which also makes the stage idempotent.
_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    semconv.GEN_AI_REQUEST_MODEL: (semconv.LLM_MODEL_NAME,),
    semconv.GEN_AI_USAGE_INPUT_TOKENS: (
        semconv.GEN_AI_USAGE_PROMPT_TOKENS,
        semconv.LLM_TOKEN_COUNT_PROMPT,
    ),
    semconv.GEN_AI_USAGE_OUTPUT_TOKENS: (
        semconv.GEN_AI_USAGE_COMPLETION_TOKENS,
        semconv.LLM_TOKEN_COUNT_COMPLETION,
    ),
}


def normalize(record: SpanRecord) -> SpanRecord:
    """Return ``record`` with variant GenAI attributes copied to canonical keys.

    Idempotent: once a canonical key holds a value, subsequent runs leave it
    untouched. A record with no recognised variants is returned unchanged.
    """
    attrs = record.attributes
    updates = {}
    for canonical, aliases in _KEY_ALIASES.items():
        if attrs.get(canonical) is not None:
            continue
        for alias in aliases:
            value = attrs.get(alias)
            if value is not None:
                updates[canonical] = value
                break

    if not updates:
        return record
    return dataclasses.replace(record, attributes={**attrs, **updates})
