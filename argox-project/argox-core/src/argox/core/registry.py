import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Tuple


@dataclass
class AgentMetadata:
    """Metadata about a registered agent."""
    name: str
    version: str
    tools: list[str]
    description: Optional[str] = None
    framework: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """
    Registry for agent metadata.
    Provides traceability required by AI Act Art. 12.
    """
    def __init__(self):
        self._agents: Dict[Tuple[str, str], AgentMetadata] = {}
        self._lock = threading.Lock()

    def register(
        self, 
        name: str, 
        version: str, 
        tools: list[str], 
        description: Optional[str] = None, 
        framework: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        tags: Optional[list[str]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Register a new agent or update an existing one."""
        if not name:
            raise ValueError("Agent name cannot be empty")
        if not version:
            raise ValueError("Agent version cannot be empty")
            
        with self._lock:
            self._agents[(name, version)] = AgentMetadata(
                name=name,
                version=version,
                tools=list(tools),
                description=description,
                framework=framework,
                model=model,
                system_prompt=system_prompt,
                tags=list(tags or []),
                config=config or {}
            )

    def get(self, name: str, version: str) -> Optional[AgentMetadata]:
        """Retrieve agent metadata by name and version."""
        with self._lock:
            return self._agents.get((name, version))

    def is_registered(self, name: str, version: str) -> bool:
        """Check if an agent is registered by name and version."""
        with self._lock:
            return (name, version) in self._agents

    def clear(self) -> None:
        """Clear all registered agents (mainly for testing)."""
        with self._lock:
            self._agents.clear()


# Global registry instance
registry = AgentRegistry()
