from typing import List, Any, Optional

from argox.interfaces.processor import ArgoxProcessor


class ArgoxManager:
    """
    Central orchestrator and state holder for the Argox SDK.
    
    ArgoxManager is the primary entry point for configuring and managing
    the Argox SDK. It maintains registries of all extension components including
    processors, plugins, exporters, and the policy client. This allows the SDK
    to operate independently of any specific AI framework while providing
    a unified interface for lifecycle management and configuration.
    """
    
    def __init__(self) -> None:
        """Initialize the ArgoxManager with empty registries."""
        self.processors: List[ArgoxProcessor] = []
        self.plugins: List[Any] = []
        self.exporters: List[Any] = []
        self.policy_client: Optional[Any] = None
    
    def register_processor(self, processor: ArgoxProcessor) -> None:
        """
        Register an ArgoxProcessor in the pipeline.
        
        Registration order matters as processors are executed sequentially
        in the order they were registered.
        
        Args:
            processor: The ArgoxProcessor instance to register.
        """
        self.processors.append(processor)
    
    def register_plugin(self, plugin: Any) -> None:
        """
        Register a plugin extension.
        
        Args:
            plugin: The plugin instance to register.
        """
        self.plugins.append(plugin)
    
    def register_exporter(self, exporter: Any) -> None:
        """
        Register an exporter extension.
        
        Args:
            exporter: The exporter instance to register.
        """
        self.exporters.append(exporter)
    
    def set_policy_client(self, client: Any) -> None:
        """
        Set the policy client for governance and auditing.
        
        Args:
            client: The policy client instance.
        """
        self.policy_client = client
    
    def clear(self) -> None:
        """
        Clear all registries and reset the configuration.
        
        This is particularly useful for isolated unit testing where
        a clean slate is needed between test cases.
        """
        self.processors.clear()
        self.plugins.clear()
        self.exporters.clear()
        self.policy_client = None
