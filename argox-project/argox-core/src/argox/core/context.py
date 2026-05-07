from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass(frozen=True)
class RunContext:
    """
    Lightweight context object carried through the SDK pipelines.
    
    RunContext enables policies and processors to make context-aware decisions
    without relying on global state. This is particularly important for
    supporting concurrent asynchronous agent executions.
    
    Metadata can hold arbitrary contextual data such as user IDs, session IDs,
    or other request-specific information needed by processors and policies.
    """
    
    run_id: str
    """A unique identifier for the current agent execution/trace."""
    
    agent_name: str
    """The name of the agent currently running."""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Dictionary to hold any additional contextual data.
    
    Note: Processors should treat this dictionary as read-only to ensure 
    execution integrity and prevent side effects across the pipeline.
    """