"""Demo showing HttpRunExporter exporting AgentRunMetrics to a local Collector.

Prerequisites:
  1. Start the local Collector (and its backing storage like Azurite if needed):
     - If using local storage backend:
       export ARGOX_STORAGE_BACKEND="local"
       export ARGOX_AUTH_ENABLED="false"
       argox-collector serve
  2. Run this script:
     python examples/demo_http_run_exporter.py
"""

import asyncio
import os

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord
from argox.exporters import HttpRunExporter


async def main():
    collector_url = os.environ.get("ARGOX_COLLECTOR_URL", "http://localhost:8000")
    print(f"Initializing HttpRunExporter pointing to: {collector_url}")

    # 1. Instantiate the HttpRunExporter
    # We set durable=True to request synchronous write confirmation from the Collector (status 200)
    exporter = HttpRunExporter(
        endpoint=collector_url,
        api_key=os.environ.get("ARGOX_COLLECTOR_API_KEY"),
        durable=True,
    )

    # 2. Create a mock run metrics object representing a completed agent run
    metrics = AgentRunMetrics(agent_name="demo-http-exporter-agent")
    metrics.agent_version = "1.0.0"
    metrics.prompt = "Tell me a joke about HTTP status codes."
    metrics.final_output = "Why did the client retry? Because the server returned a 500!"
    metrics.success = True

    # Add dummy token usage
    metrics.api_calls.append(
        ApiCallRecord(call_number=1, input_tokens=45, output_tokens=30, total_tokens=75)
    )
    # Add dummy tool calls
    metrics.tools_available = ["get_joke_category"]
    metrics.tools_called.append(
        ToolCallRecord(name="get_joke_category", start=1700000000.0, end=1700000000.2, result="HTTP")
    )

    print("\nSimulating agent run completion...")
    print(f"Run ID: {metrics.run_id}")
    print(f"Tokens: Input={metrics.total_input_tokens}, Output={metrics.total_output_tokens}")

    # 3. Export the metrics
    print("\nExporting metrics via HttpRunExporter...")
    exporter.export(metrics)

    # 4. Check for exporter errors
    if metrics.exporter_errors:
        print("\n❌ Export failed with errors:")
        for err in metrics.exporter_errors:
            print(f"  - {err}")
    else:
        print(f"\n✅ Export successful! The run record has been posted to {collector_url}/v1/runs")
        print("You can verify it landed by querying the Collector:")
        print(f"  curl {collector_url}/api/v1/runs/{metrics.run_id}")


if __name__ == "__main__":
    asyncio.run(main())
