"""Test for tool cache refresh bug with nested handler invocation (issue #1298).

This test verifies that cache refresh doesn't use nested handler invocation,
which can disrupt async execution in streaming contexts.
"""

from typing import Any

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.types import ListToolsRequest, TextContent, Tool


@pytest.mark.anyio
async def test_no_nested_handler_invocation_on_cache_refresh():
    """Verify that cache refresh doesn't use nested handler invocation.
    
    Issue #1298: Tool handlers can fail when cache refresh triggers
    nested handler invocation via self.request_handlers[ListToolsRequest](None),
    which disrupts async execution flow in streaming contexts.
    
    This test verifies the fix by detecting whether nested handler
    invocation occurs during cache refresh.
    """
    server = Server("test-server")
    
    # Track handler invocations
    handler_invocations = []
    
    @server.list_tools()
    async def list_tools():
        # Normal tool listing
        await anyio.sleep(0.001)
        return [
            Tool(
                name="test_tool",
                description="Test tool",
                inputSchema={"type": "object", "properties": {}}
            )
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        # Simple tool implementation
        return [TextContent(type="text", text="Tool result")]
    
    # Intercept the ListToolsRequest handler to detect nested invocation
    original_handler = None
    
    def setup_handler_interceptor():
        nonlocal original_handler
        original_handler = server.request_handlers.get(ListToolsRequest)
        
        async def interceptor(req):
            # Track the invocation
            # req is None for nested invocations (the problematic pattern)
            # req is a proper request object for normal invocations
            if req is None:
                handler_invocations.append("nested")
            else:
                handler_invocations.append("normal")
            
            # Call the original handler
            if original_handler:
                return await original_handler(req)
            return None
        
        server.request_handlers[ListToolsRequest] = interceptor
    
    # Set up the interceptor after decorators have run
    setup_handler_interceptor()
    
    # Setup communication channels
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from mcp.shared.message import SessionMessage
    
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    
    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options()
        )
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        
        async with ClientSession(server_to_client_receive, client_to_server_send) as session:
            await session.initialize()
            
            # Clear the cache to force a refresh on next tool call
            server._tool_cache.clear()
            
            # Make a tool call - this should trigger cache refresh
            result = await session.call_tool("test_tool", {})
            
            # Verify the tool call succeeded
            assert result is not None
            assert not result.isError
            assert result.content[0].text == "Tool result"
            
            # Check if nested handler invocation occurred
            has_nested_invocation = "nested" in handler_invocations
            
            # The bug is present if nested handler invocation occurs
            assert not has_nested_invocation, (
                "Nested handler invocation detected during cache refresh. "
                "This pattern (calling request_handlers[ListToolsRequest](None)) "
                "can disrupt async execution in streaming contexts (issue #1298)."
            )
        
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_concurrent_cache_refresh_safety():
    """Verify that concurrent tool calls with cache refresh work correctly.
    
    Multiple concurrent tool calls that all trigger cache refresh should
    not cause issues or result in nested handler invocations.
    """
    server = Server("test-server")
    
    # Track concurrent handler invocations
    nested_invocations = 0
    
    @server.list_tools()
    async def list_tools():
        await anyio.sleep(0.01)  # Simulate some async work
        return [
            Tool(
                name=f"tool_{i}",
                description=f"Tool {i}",
                inputSchema={"type": "object", "properties": {}}
            )
            for i in range(3)
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        await anyio.sleep(0.001)
        return [TextContent(type="text", text=f"Result from {name}")]
    
    # Intercept handler to detect nested invocations
    original_handler = server.request_handlers.get(ListToolsRequest)
    
    async def interceptor(req):
        nonlocal nested_invocations
        if req is None:
            nested_invocations += 1
        if original_handler:
            return await original_handler(req)
        return None
    
    if original_handler:
        server.request_handlers[ListToolsRequest] = interceptor
    
    # Setup communication
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from mcp.shared.message import SessionMessage
    
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    
    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options()
        )
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        
        async with ClientSession(server_to_client_receive, client_to_server_send) as session:
            await session.initialize()
            
            # Clear cache to force refresh
            server._tool_cache.clear()
            
            # Make concurrent tool calls
            import asyncio
            results = await asyncio.gather(
                session.call_tool("tool_0", {}),
                session.call_tool("tool_1", {}),
                session.call_tool("tool_2", {}),
                return_exceptions=True
            )
            
            # Verify all calls succeeded
            for i, result in enumerate(results):
                assert not isinstance(result, Exception), f"Tool {i} failed: {result}"
                assert not result.isError
                assert f"tool_{i}" in result.content[0].text
            
            # Verify no nested invocations occurred
            assert nested_invocations == 0, (
                f"Detected {nested_invocations} nested handler invocations "
                "during concurrent cache refresh. This indicates the bug from "
                "issue #1298 is present."
            )
        
        tg.cancel_scope.cancel()