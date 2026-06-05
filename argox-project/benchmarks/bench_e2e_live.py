"""Strategy B: real API E2E benchmarks (Azure AI Foundry).

The deployment is an Azure AI Foundry model exposed over the
OpenAI-compatible surface, so we talk to it with a plain ``AsyncOpenAI``
client pointed at the endpoint via ``base_url`` — not ``AsyncAzureOpenAI``,
which rewrites the path to ``/openai/deployments/...?api-version`` that
Foundry does not serve. This mirrors the demo's client setup.

Requires ``ARGOX_LIVE_BENCH=1``. LLM response variance dominates SDK cost
(~1ms), so N>=5 rounds is the minimum for any significance. ``pedantic`` pins
rounds/iterations so the call count (and therefore cost) is deterministic:
6 billable calls per test (5 timed + 1 warmup, 1 iteration each).

Cost per full run (both tests, gpt-4o-mini deployment, 200-token cap):
12 calls / well under one US cent. See ``.untracked/`` notes.

Required environment (supplied via .env, like the demo):
    ARGOX_LIVE_BENCH=1
    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_ENDPOINT=<OpenAI-compatible Foundry base URL>
    AZURE_OPENAI_DEPLOYMENT=<deployment-name>

Run and persist results:
    cd argox-project
    ARGOX_LIVE_BENCH=1 pytest benchmarks/bench_e2e_live.py -v \\
        --benchmark-columns=mean,median,stddev,min,max,rounds \\
        --benchmark-json=../.untracked/live-results.json

LLM outliers inflate the mean, so read the median (robust central value) and
the min (cleanest overhead signal), not the mean.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Load Azure credentials from .env (matching the demo's workflow) only when the
# live gate is on, so a normal test run neither mutates the process env nor
# accidentally enables billable calls. python-dotenv is optional; if absent,
# fall back to whatever is already exported.
if os.getenv("ARGOX_LIVE_BENCH"):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

pytestmark = pytest.mark.skipif(
    not os.getenv("ARGOX_LIVE_BENCH"),
    reason="set ARGOX_LIVE_BENCH=1 to run live API benchmarks",
)

# Small, deterministic workload — we measure latency, not answer quality.
_INSTRUCTIONS = "You are a concise assistant. Answer in one short sentence."
_PROMPT = "In one sentence, what is observability in software systems?"
_MAX_TOKENS = 200


def _require(name: str) -> str:
    """Return an env var or skip the test loudly if it is missing."""
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} not set — required for live Foundry benchmarks")
    return value


def _openai_client():
    """Build an AsyncOpenAI client pointed at the Foundry endpoint.

    The model is an Azure AI Foundry deployment on the OpenAI-compatible
    surface, so we use a plain ``AsyncOpenAI`` with ``base_url`` set to the
    endpoint — not ``AsyncAzureOpenAI``. Mirrors the demo's
    ``set_default_openai_client`` setup. Imported lazily so the module skips
    cleanly on a machine without ``openai`` installed.
    """
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key=_require("AZURE_OPENAI_API_KEY"),
        base_url=_require("AZURE_OPENAI_ENDPOINT"),
    )


@pytest.mark.benchmark(group="live")
def test_live_bare_openai(benchmark):
    """Baseline: raw Foundry chat-completions call, no SDK wrapping."""
    client = _openai_client()
    deployment = _require("AZURE_OPENAI_DEPLOYMENT")

    async def _call():
        return await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _INSTRUCTIONS},
                {"role": "user", "content": _PROMPT},
            ],
            max_tokens=_MAX_TOKENS,
        )

    # pedantic() pins the call count so cost is deterministic: 5 timed rounds
    # + 1 warmup, 1 iteration each = 6 billable calls. (rounds/iterations are
    # not accepted on the @benchmark marker, only here.)
    result = benchmark.pedantic(
        lambda: asyncio.run(_call()),
        rounds=5,
        warmup_rounds=1,
        iterations=1,
    )
    assert result.choices[0].message.content


@pytest.mark.benchmark(group="live")
def test_live_sdk_wrapped(benchmark):
    """SDK-wrapped call. Compare mean to test_live_bare_openai to get overhead.

    Runs through a bare ArgoxManager (openai plugin only, no processors or
    policy) so the delta against the bare baseline isolates pure lifecycle
    overhead rather than feature cost.
    """
    from agents import (
        Agent,
        ModelSettings,
        Runner,
        set_default_openai_client,
        set_tracing_disabled,
    )

    from argox.core.manager import ArgoxManager
    from argox_openai import ArgoxOpenAIPlugin

    # Match the demo: register the Foundry-backed client as the agents SDK
    # default and reference the deployment by name. Tracing is disabled so the
    # SDK makes exactly one billable call per round and needs no second
    # (OpenAI) credential for trace upload.
    set_tracing_disabled(True)
    set_default_openai_client(_openai_client())

    agent = Agent(
        name="bench-agent",
        instructions=_INSTRUCTIONS,
        model=_require("AZURE_OPENAI_DEPLOYMENT"),
        model_settings=ModelSettings(max_tokens=_MAX_TOKENS),
    )

    manager = ArgoxManager()
    manager.register_plugin(ArgoxOpenAIPlugin())

    async def _runner(instrumented, prompt: str):
        return await Runner.run(instrumented, prompt)

    async def _one():
        return await manager.run(agent, _PROMPT, "openai", _runner)

    output = benchmark.pedantic(
        lambda: asyncio.run(_one()),
        rounds=5,
        warmup_rounds=1,
        iterations=1,
    )
    assert output
