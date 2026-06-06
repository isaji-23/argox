from dataclasses import dataclass
from typing import Dict, Optional, Any, Callable


@dataclass
class AgentMetadata:
    """Metadata about a registered agent."""
    name: str
    version: str
    tools: list[str]
    description: Optional[str] = None
    framework: Optional[str] = None


class AgentRegistry:
    """
    Registry for agent metadata.
    Provides traceability required by AI Act Art. 12.
    """
    def __init__(self):
        self._agents: Dict[str, AgentMetadata] = {}

    def register(self, name: str, version: str, tools: list[str], description: Optional[str] = None, framework: Optional[str] = None) -> None:
        """Register a new agent or update an existing one."""
        self._agents[name] = AgentMetadata(
            name=name,
            version=version,
            tools=tools,
            description=description,
            framework=framework
        )

    def get(self, name: str) -> Optional[AgentMetadata]:
        """Retrieve agent metadata by name."""
        return self._agents.get(name)

    def is_registered(self, name: str) -> bool:
        """Check if an agent is registered."""
        return name in self._agents

    def clear(self) -> None:
        """Clear all registered agents (mainly for testing)."""
        self._agents.clear()


# Global registry instance
registry = AgentRegistry()
