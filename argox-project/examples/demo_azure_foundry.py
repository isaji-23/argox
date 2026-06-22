"""
Demo: Azure AI Foundry Agent Service integration with Argox.

This script demonstrates how to instrument an Azure AI Foundry agent with Argox
for monitoring and governance (PII redaction and policy enforcement).

Requirements:
    pip install argox-core argox-plugin-azure-foundry azure-ai-projects azure-identity
"""

import asyncio
import os
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AsyncFunctionTool
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from argox import ArgoxManager
from argox.core import init_telemetry
from argox.observability import ConsoleSpanLogger
from argox_azure_foundry import ArgoxAzureFoundryPlugin

# 1. Setup Argox Telemetry
init_telemetry(exporters=[ConsoleSpanLogger()])

async def get_weather(location: str):
    """Get the current weather in a given location."""
    return f"The weather in {location} is sunny with a high of 25°C."

async def main():
    load_dotenv()
    
    # Connection string from Azure AI Foundry project
    conn_str = os.getenv("AZURE_AI_PROJECT_CONNECTION_STRING")
    if not conn_str:
        print("Please set AZURE_AI_PROJECT_CONNECTION_STRING in your .env file")
        return

    async with AIProjectClient.from_connection_string(
        conn_str=conn_str,
        credential=DefaultAzureCredential()
    ) as client:
        
        # 2. Define tools
        weather_tool = AsyncFunctionTool(functions=[get_weather])
        
        # 3. Create Agent
        agent = await client.agents.create_agent(
            model="gpt-4o",
            name="weather-assistant",
            instructions="You are a helpful assistant that can provide weather information.",
            tools=[weather_tool]
        )
        print(f"Created agent: {agent.id}")

        # 4. Initialize Argox Manager
        # In a real scenario, you'd register processors and policies here.
        manager = ArgoxManager()
        manager.register_plugin(ArgoxAzureFoundryPlugin())

        # 5. Execute Run with Argox monitoring
        prompt = "What's the weather like in Madrid?"
        
        async def foundry_runner(instrumented_agent, processed_prompt):
            # Create a thread
            thread = await client.agents.create_thread()
            
            # Add user message
            await client.agents.create_message(
                thread_id=thread.id,
                role="user",
                content=processed_prompt
            )
            
            # Create and process run
            # Note: We use the instrumented_agent passed by the manager
            run = await client.agents.create_and_process_run(
                thread_id=thread.id,
                agent_id=instrumented_agent.id
            )
            
            # Retrieve final message content to return to the manager
            messages = await client.agents.list_messages(thread_id=thread.id)
            final_content = ""
            for msg in messages.data:
                if msg.role == "assistant" and msg.content:
                    final_content = msg.content[0].text.value
                    break
            
            # We return the run object as 'raw_result' for token extraction
            # and the final content as a result.
            # ArgoxManager expects the runner to return what plugin.extract_tokens/output will use.
            # In our case, extract_tokens uses the run object.
            # We wrap it in an object that extract_output can also use.
            class RunResult:
                def __init__(self, run, content):
                    self.usage = run.usage
                    self.content = content
            
            return RunResult(run, final_content)

        try:
            print(f"Running prompt: {prompt}")
            response = await manager.run(
                agent=agent,
                prompt=prompt,
                plugin_name="azure-foundry",
                runner=foundry_runner
            )
            print(f"Agent Response: {response}")
        finally:
            # Cleanup
            await client.agents.delete_agent(agent.id)

if __name__ == "__main__":
    asyncio.run(main())
