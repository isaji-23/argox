# argox-plugin-openai

Official Argox plugin for the OpenAI Agents SDK.

Bridges the OpenAI Agents SDK (`agents.Agent`, `agents.Runner`, `agents.lifecycle.AgentHooks`) to the Argox SDK so that `ArgoxManager` can drive agents from the OpenAI ecosystem.

## Install

```bash
pip install -e .[dev]
```

## Usage

```python
from argox.core import ArgoxManager
from argox_openai import ArgoxOpenAIPlugin
from agents import Agent, Runner

mgr = ArgoxManager()
mgr.register_plugin(ArgoxOpenAIPlugin())

agent = Agent(name="assistant", instructions="...", model="gpt-4o-mini")

async def run_with_openai(agent, prompt):
    return await Runner.run(agent, prompt)

result = await mgr.run(agent, "hello", "openai", run_with_openai)
```
