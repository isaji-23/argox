from argox.core.registry import AgentRegistry, AgentMetadata, registry

def test_agent_registry_register_and_get():
    # Fresh registry for testing
    test_registry = AgentRegistry()
    
    test_registry.register(
        name="test-agent",
        version="1.0.0",
        tools=["tool1", "tool2"],
        description="A test agent",
        framework="openai",
        model="gpt-4o",
        system_prompt="You are a helpful assistant.",
        tags=["test", "v1"],
        temperature=0.7,
        author="QA Team"
    )
    
    assert test_registry.is_registered("test-agent")
    
    metadata = test_registry.get("test-agent")
    assert metadata is not None
    assert metadata.name == "test-agent"
    assert metadata.version == "1.0.0"
    assert metadata.tools == ["tool1", "tool2"]
    assert metadata.description == "A test agent"
    assert metadata.framework == "openai"
    assert metadata.model == "gpt-4o"
    assert metadata.system_prompt == "You are a helpful assistant."
    assert metadata.tags == ["test", "v1"]
    assert metadata.config == {"temperature": 0.7, "author": "QA Team"}

def test_agent_registry_get_unregistered():
    test_registry = AgentRegistry()
    assert test_registry.get("unknown-agent") is None
    assert not test_registry.is_registered("unknown-agent")

def test_agent_registry_clear():
    test_registry = AgentRegistry()
    test_registry.register("agent1", "1.0", [])
    assert test_registry.is_registered("agent1")
    
    test_registry.clear()
    assert not test_registry.is_registered("agent1")
    assert test_registry.get("agent1") is None

def test_global_registry_instance():
    # Verify the global instance is exported and works
    registry.clear()
    registry.register("global-agent", "1.0", [])
    assert registry.is_registered("global-agent")
    registry.clear()
