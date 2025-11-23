"""
Example demonstrating per-request headers functionality for MCP client.

Shows how to use the extra_headers parameter to send different HTTP headers
with each request, enabling use cases like per-user authentication, request
tracing, A/B testing, and multi-tenant applications.
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    """Demonstrate per-request headers functionality."""

    # Connection-level headers (static for the entire session)
    connection_headers = {"Authorization": "Bearer org-level-token", "X-Org-ID": "org-123"}

    async with streamablehttp_client("https://mcp.example.com/mcp", headers=connection_headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Example 1: Request tracing
            tracing_headers = {
                "X-Request-ID": "req-12345",
                "X-Trace-ID": "trace-abc-456",
            }
            result = await session.call_tool("process_data", {"type": "analytics"}, extra_headers=tracing_headers)
            print(f"Traced request result: {result}")

            # Example 2: User-specific authentication
            user_headers = {
                "X-User-ID": "alice",
                "X-Auth-Token": "user-token-12345",
            }
            result = await session.call_tool("get_user_data", {"fields": ["profile"]}, extra_headers=user_headers)
            print(f"User-specific result: {result}")

            # Example 3: A/B testing
            experiment_headers = {
                "X-Experiment-ID": "new-ui-test",
                "X-Variant": "variant-b",
            }
            result = await session.call_tool(
                "get_recommendations", {"user_id": "user123"}, extra_headers=experiment_headers
            )
            print(f"A/B test result: {result}")

            # Example 4: Override connection-level headers
            override_headers = {
                "Authorization": "Bearer user-specific-token",  # Overrides connection-level
                "X-Special-Permission": "admin",
            }
            result = await session.call_tool("admin_operation", {"operation": "reset"}, extra_headers=override_headers)
            print(f"Admin operation result: {result}")

            # Example 5: Works with all ClientSession methods
            await session.list_resources(extra_headers={"X-Resource-Filter": "public"})
            await session.get_prompt("template", extra_headers={"X-Context": "help"})
            await session.set_logging_level("debug", extra_headers={"X-Debug-Session": "true"})


if __name__ == "__main__":
    print("MCP Client Per-Request Headers Example")
    print("=" * 50)

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Example requires a running MCP server. Error: {e}")
        print("\nThis example demonstrates the API usage patterns.")
