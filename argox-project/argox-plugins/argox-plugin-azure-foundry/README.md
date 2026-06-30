# argox-plugin-azure-foundry

Argox plugin for Azure AI Foundry Agent Service (`azure-ai-projects`).

## Installation

```bash
pip install argox-plugin-azure-foundry
```

## Usage

```python
from argox import ArgoxManager
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

# ... initialize client and agent ...

manager = ArgoxManager(plugins=["azure-foundry"])

with manager.run(agent) as metrics:
    # Use the agent through the manager or directly if instrumented
    pass
```
