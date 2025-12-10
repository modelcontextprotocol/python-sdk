"""
Test for issue #262: MCP Client Tool Call Hang

Problem: await session.call_tool() gets stuck without returning a response,
while await session.list_tools() works properly. The server executes successfully
and produces results, but the client cannot receive them.

Key observations from the issue:
- list_tools() works
- call_tool() hangs (never returns)
- Debugger stepping makes the issue disappear (timing/race condition)
- Works on native Windows, fails on WSL Ubuntu
- Affects both stdio and SSE transports

Possible causes investigated:
1. Stdout buffering - Server not flushing stdout after responses
2. Race condition - Timing-sensitive issue in async message handling
3. 0-capacity streams - stdio_client uses unbuffered streams that require
   strict handshaking between sender and receiver
4. Interleaved notifications - Server sending notifications during tool execution
5. Bidirectional communication - Server requesting sampling during tool execution

The tests below attempt to reproduce the issue in various scenarios.
These tests pass in the test environment, which suggests the issue may be:
- Environment-specific (WSL vs Windows)
- Already fixed in recent versions
- Dependent on specific server implementations

A standalone reproduction script is available at:
    tests/issues/reproduce_262_standalone.py

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
"""

import sys
import textwrap

import anyio
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Minimal MCP server that handles initialization and tool calls
MINIMAL_SERVER_SCRIPT = textwrap.dedent('''
    import json
    import sys

    def send_response(response):
        """Send a JSON-RPC response to stdout."""
        print(json.dumps(response), flush=True)

    def read_request():
        """Read a JSON-RPC request from stdin."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                # No response for notifications
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "echo",
                            "description": "Echo the input",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # Simulate some processing time
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Hello from tool"}],
                        "isError": False
                    }
                })
            elif method == "ping":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                })
            else:
                # Unknown method
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
''').strip()


@pytest.mark.anyio
async def test_list_tools_then_call_tool_basic():
    """
    Basic test: list_tools() followed by call_tool().
    This is the scenario from issue #262.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # This should work
                tools = await session.list_tools()
                assert len(tools.tools) == 1
                assert tools.tools[0].name == "echo"

                # This is where the hang was reported
                result = await session.call_tool("echo", arguments={})
                assert result.content[0].text == "Hello from tool"


# Server that sends log messages during tool execution
# This tests whether notifications during tool execution cause issues
SERVER_WITH_LOGS_SCRIPT = textwrap.dedent('''
    import json
    import sys

    def send_message(message):
        """Send a JSON-RPC message to stdout."""
        print(json.dumps(message), flush=True)

    def read_request():
        """Read a JSON-RPC request from stdin."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}, "logging": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "log_tool",
                            "description": "Tool that sends log messages",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # Send log notifications before the response
                for i in range(3):
                    send_message({
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {
                            "level": "info",
                            "data": f"Log message {i}"
                        }
                    })

                # Then send the response
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Done with logs"}],
                        "isError": False
                    }
                })
            elif method == "ping":
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                })
            else:
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
''').strip()


@pytest.mark.anyio
async def test_tool_call_with_log_notifications():
    """
    Test tool call when server sends log notifications during execution.
    This tests whether interleaved notifications cause the hang.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_WITH_LOGS_SCRIPT],
    )

    log_messages = []

    async def logging_callback(params):
        log_messages.append(params.data)

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, logging_callback=logging_callback) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("log_tool", arguments={})
                assert result.content[0].text == "Done with logs"

                # Verify log messages were received
                assert len(log_messages) == 3


# Server that sends responses without flush
# This tests the buffering theory
SERVER_NO_FLUSH_SCRIPT = textwrap.dedent('''
    import json
    import sys

    def send_response_no_flush(response):
        """Send a JSON-RPC response WITHOUT flushing."""
        print(json.dumps(response))
        # Note: no sys.stdout.flush() here!

    def send_response_with_flush(response):
        """Send a JSON-RPC response with flush."""
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        request_count = 0
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")
            request_count += 1

            if method == "initialize":
                send_response_with_flush({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                # list_tools response - with flush (works)
                send_response_with_flush({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "test_tool",
                            "description": "Test tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # call_tool response - NO flush (might hang!)
                send_response_no_flush({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Tool result"}],
                        "isError": False
                    }
                })
                # Force flush after to avoid permanent hang in test
                sys.stdout.flush()
            else:
                send_response_with_flush({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
''').strip()


@pytest.mark.anyio
async def test_tool_call_with_buffering():
    """
    Test tool call when server doesn't flush immediately.
    This tests the stdout buffering theory.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_NO_FLUSH_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("test_tool", arguments={})
                assert result.content[0].text == "Tool result"


# Server that uses unbuffered output mode
SERVER_UNBUFFERED_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import os

    # Attempt to make stdout unbuffered
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

    def send_response(response):
        print(json.dumps(response))

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "test_tool",
                            "description": "Test tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Unbuffered result"}],
                        "isError": False
                    }
                })
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_tool_call_with_line_buffered_output():
    """
    Test tool call with line-buffered stdout.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-c", SERVER_UNBUFFERED_SCRIPT],  # -u for unbuffered
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("test_tool", arguments={})
                assert result.content[0].text == "Unbuffered result"


# Server that simulates slow tool execution
SERVER_SLOW_TOOL_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import time

    def send_response(response):
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "slow_tool",
                            "description": "Slow tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # Simulate slow tool execution
                time.sleep(0.5)
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Slow result"}],
                        "isError": False
                    }
                })
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_tool_call_slow_execution():
    """
    Test tool call with slow execution time.
    This might expose race conditions related to timing.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_SLOW_TOOL_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("slow_tool", arguments={})
                assert result.content[0].text == "Slow result"


# Server that sends rapid tool responses (stress test)
@pytest.mark.anyio
async def test_rapid_tool_calls():
    """
    Test rapid successive tool calls.
    This might expose race conditions in message handling.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                # Rapid sequential calls
                for i in range(10):
                    result = await session.call_tool("echo", arguments={})
                    assert result.content[0].text == "Hello from tool"


@pytest.mark.anyio
async def test_concurrent_tool_calls():
    """
    Test concurrent tool calls.
    This might expose race conditions in message handling.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                # Concurrent calls
                async with anyio.create_task_group() as tg:
                    results = []

                    async def call_tool_and_store():
                        result = await session.call_tool("echo", arguments={})
                        results.append(result)

                    for _ in range(5):
                        tg.start_soon(call_tool_and_store)

                assert len(results) == 5
                for result in results:
                    assert result.content[0].text == "Hello from tool"


# Server that sends a sampling request during tool execution
# This is a more complex scenario that might trigger the original issue
SERVER_WITH_SAMPLING_SCRIPT = textwrap.dedent('''
    import json
    import sys
    import threading

    # Global request ID counter
    next_request_id = 100

    def send_message(message):
        """Send a JSON-RPC message to stdout."""
        json_str = json.dumps(message)
        print(json_str, flush=True)

    def read_message():
        """Read a JSON-RPC message from stdin."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        global next_request_id

        while True:
            message = read_message()
            if message is None:
                break

            method = message.get("method", "")
            request_id = message.get("id")

            if method == "initialize":
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "sampling_tool",
                            "description": "Tool that requests sampling",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # During tool execution, send a sampling request to the client
                sampling_request_id = next_request_id
                next_request_id += 1

                # Send sampling request
                send_message({
                    "jsonrpc": "2.0",
                    "id": sampling_request_id,
                    "method": "sampling/createMessage",
                    "params": {
                        "messages": [
                            {"role": "user", "content": {"type": "text", "text": "Hello"}}
                        ],
                        "maxTokens": 100
                    }
                })

                # Wait for sampling response
                while True:
                    response = read_message()
                    if response is None:
                        break
                    # Check if this is our sampling response
                    if response.get("id") == sampling_request_id:
                        # Got sampling response, now send tool result
                        send_message({
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [{"type": "text", "text": "Tool done after sampling"}],
                                "isError": False
                            }
                        })
                        break
                    # Otherwise it might be another request, ignore for simplicity
            elif method == "ping":
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                })
            else:
                send_message({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
''').strip()


@pytest.mark.anyio
async def test_tool_call_with_sampling_request():
    """
    Test tool call when server sends a sampling request during execution.

    This is the scenario from the original issue #262 where:
    1. Client calls tool
    2. Server sends sampling/createMessage request to client
    3. Client responds with sampling result
    4. Server sends tool result

    This bidirectional communication during tool execution could cause deadlock.
    """
    import mcp.types as types
    from mcp.shared.context import RequestContext

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_WITH_SAMPLING_SCRIPT],
    )

    async def sampling_callback(
        context: "RequestContext",
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult:
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="Hello from model"),
            model="gpt-3.5-turbo",
            stopReason="endTurn",
        )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, sampling_callback=sampling_callback) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                # This is where the potential deadlock could occur
                result = await session.call_tool("sampling_tool", arguments={})
                assert result.content[0].text == "Tool done after sampling"


# Server that delays response to trigger timing issues
# This tests the race condition theory more directly
SERVER_TIMING_RACE_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import time

    def send_response(response):
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    # Track initialization timing
    initialized_time = None

    def main():
        global initialized_time

        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                initialized_time = time.time()
            elif method == "tools/list":
                # If tools/list comes very quickly after initialized,
                # respond immediately
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "timing_tool",
                            "description": "Tool to test timing",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # Small delay to potentially trigger race
                time.sleep(0.001)
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Timing result"}],
                        "isError": False
                    }
                })
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_timing_race_condition():
    """
    Test rapid sequence of operations that might trigger timing issues.
    The issue mentions that debugger stepping makes the issue disappear,
    suggesting timing sensitivity.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_TIMING_RACE_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                # Rapid fire of operations
                await session.initialize()

                # Immediately call list_tools and call_tool with no delays
                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("timing_tool", arguments={})
                assert result.content[0].text == "Timing result"


@pytest.mark.anyio
async def test_multiple_sessions_stress():
    """
    Stress test: create multiple sessions to different server instances.
    This might expose any global state or resource contention issues.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    async def run_session():
        with anyio.fail_after(10):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert len(tools.tools) == 1
                    result = await session.call_tool("echo", arguments={})
                    assert result.content[0].text == "Hello from tool"

    # Run multiple sessions concurrently
    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(run_session)


# Test with 0-capacity streams like the real stdio_client uses
# This is important because the memory transport uses capacity 1, which has different behavior
@pytest.mark.anyio
async def test_zero_capacity_streams():
    """
    Test using 0-capacity streams like the real stdio_client.

    The memory transport tests use capacity 1, but stdio_client uses 0.
    This difference might explain why tests pass but real usage hangs.
    """
    import mcp.types as types
    from mcp.server.models import InitializationOptions
    from mcp.server.session import ServerSession
    from mcp.shared.message import SessionMessage
    from mcp.shared.session import RequestResponder
    from mcp.types import ServerCapabilities, Tool

    # Create 0-capacity streams like stdio_client does
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)

    tool_call_success = False

    async def run_server():
        nonlocal tool_call_success

        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools=types.ToolsCapability(listChanged=False),
                ),
            ),
        ) as server_session:
            message_count = 0
            async for message in server_session.incoming_messages:
                if isinstance(message, Exception):
                    raise message

                message_count += 1

                if isinstance(message, RequestResponder):
                    if isinstance(message.request.root, types.ListToolsRequest):
                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.ListToolsResult(
                                        tools=[
                                            Tool(
                                                name="test_tool",
                                                description="Test tool",
                                                inputSchema={"type": "object", "properties": {}},
                                            )
                                        ]
                                    )
                                )
                            )
                    elif isinstance(message.request.root, types.CallToolRequest):
                        tool_call_success = True
                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.CallToolResult(
                                        content=[types.TextContent(type="text", text="Tool result")],
                                        isError=False,
                                    )
                                )
                            )
                        # Exit after tool call
                        return

    async def run_client():
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session:
            await session.initialize()

            tools = await session.list_tools()
            assert len(tools.tools) == 1

            result = await session.call_tool("test_tool", arguments={})
            assert result.content[0].text == "Tool result"

    with anyio.fail_after(10):
        async with (
            client_to_server_send,
            client_to_server_receive,
            server_to_client_send,
            server_to_client_receive,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(run_server)
            tg.start_soon(run_client)

    assert tool_call_success


@pytest.mark.anyio
async def test_zero_capacity_with_rapid_responses():
    """
    Test 0-capacity streams with rapid server responses.

    This tests the theory that rapid responses before the client
    is ready to receive might cause issues.
    """
    import mcp.types as types
    from mcp.server.models import InitializationOptions
    from mcp.server.session import ServerSession
    from mcp.shared.message import SessionMessage
    from mcp.shared.session import RequestResponder
    from mcp.types import ServerCapabilities, Tool

    # Create 0-capacity streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)

    tool_call_count = 0
    expected_tool_calls = 3

    async def run_server():
        nonlocal tool_call_count

        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools=types.ToolsCapability(listChanged=False),
                ),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                if isinstance(message, Exception):
                    raise message

                if isinstance(message, RequestResponder):
                    if isinstance(message.request.root, types.ListToolsRequest):
                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.ListToolsResult(
                                        tools=[
                                            Tool(
                                                name="rapid_tool",
                                                description="Rapid tool",
                                                inputSchema={"type": "object", "properties": {}},
                                            )
                                        ]
                                    )
                                )
                            )
                    elif isinstance(message.request.root, types.CallToolRequest):
                        tool_call_count += 1
                        # Respond immediately without any delay
                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.CallToolResult(
                                        content=[types.TextContent(type="text", text="Rapid result")],
                                        isError=False,
                                    )
                                )
                            )
                        # Exit after all expected tool calls
                        if tool_call_count >= expected_tool_calls:
                            return

    async def run_client():
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session:
            await session.initialize()

            # Rapid sequence of operations
            tools = await session.list_tools()
            assert len(tools.tools) == 1

            # Call tool multiple times rapidly
            for _ in range(expected_tool_calls):
                result = await session.call_tool("rapid_tool", arguments={})
                assert result.content[0].text == "Rapid result"

    with anyio.fail_after(10):
        async with (
            client_to_server_send,
            client_to_server_receive,
            server_to_client_send,
            server_to_client_receive,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(run_server)
            tg.start_soon(run_client)

    assert tool_call_count == expected_tool_calls


@pytest.mark.anyio
async def test_zero_capacity_with_notifications():
    """
    Test 0-capacity streams with interleaved notifications.

    The server sends notifications during tool execution,
    which might interfere with response handling.
    """
    import mcp.types as types
    from mcp.server.models import InitializationOptions
    from mcp.server.session import ServerSession
    from mcp.shared.message import SessionMessage
    from mcp.shared.session import RequestResponder
    from mcp.types import ServerCapabilities, Tool

    # Create 0-capacity streams
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)

    notifications_sent = 0

    async def run_server():
        nonlocal notifications_sent

        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools=types.ToolsCapability(listChanged=False),
                    logging=types.LoggingCapability(),
                ),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                if isinstance(message, Exception):
                    raise message

                if isinstance(message, RequestResponder):
                    if isinstance(message.request.root, types.ListToolsRequest):
                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.ListToolsResult(
                                        tools=[
                                            Tool(
                                                name="notifying_tool",
                                                description="Tool that sends notifications",
                                                inputSchema={"type": "object", "properties": {}},
                                            )
                                        ]
                                    )
                                )
                            )
                    elif isinstance(message.request.root, types.CallToolRequest):
                        # Send notifications before response
                        for i in range(3):
                            await server_session.send_log_message(
                                level="info",
                                data=f"Log {i}",
                            )
                            notifications_sent += 1

                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.CallToolResult(
                                        content=[types.TextContent(type="text", text="Done with notifications")],
                                        isError=False,
                                    )
                                )
                            )
                        return

    log_messages = []

    async def log_callback(params):
        log_messages.append(params.data)

    async def run_client():
        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            logging_callback=log_callback,
        ) as session:
            await session.initialize()

            tools = await session.list_tools()
            assert len(tools.tools) == 1

            result = await session.call_tool("notifying_tool", arguments={})
            assert result.content[0].text == "Done with notifications"

    with anyio.fail_after(10):
        async with (
            client_to_server_send,
            client_to_server_receive,
            server_to_client_send,
            server_to_client_receive,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(run_server)
            tg.start_soon(run_client)

    assert notifications_sent == 3
    assert len(log_messages) == 3


# =============================================================================
# AGGRESSIVE TESTS BASED ON ISSUE #1764 INSIGHTS
# =============================================================================
# Issue #1764 reveals that zero-buffer streams + start_soon can cause deadlocks
# when sender is faster than receiver initialization.


# Server that responds INSTANTLY - no processing delay at all
SERVER_INSTANT_RESPONSE_SCRIPT = textwrap.dedent("""
    import json
    import sys

    def send_response(response):
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "instant-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "instant_tool",
                            "description": "Instant tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Instant result"}],
                        "isError": False
                    }
                })
            elif method == "ping":
                send_response({"jsonrpc": "2.0", "id": request_id, "result": {}})

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_instant_server_response():
    """
    Test with a server that responds as fast as possible.

    This tests the #1764 scenario where the sender is faster than
    the receiver can initialize.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_INSTANT_RESPONSE_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("instant_tool", arguments={})
                assert result.content[0].text == "Instant result"


# Server that adds big delays to test timing sensitivity
SERVER_BIG_DELAYS_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import time

    def send_response(response):
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                # 2 second delay before responding
                time.sleep(2)
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "slow-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                # 2 second delay
                time.sleep(2)
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "slow_tool",
                            "description": "Slow tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # 3 second delay - this is where the original issue might manifest
                time.sleep(3)
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Slow result after 3 seconds"}],
                        "isError": False
                    }
                })
            elif method == "ping":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                })

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_server_with_big_delays():
    """
    Test with a server that has significant delays (2-3 seconds).

    As mentioned in issue comments, debugger stepping (which adds delays)
    makes the issue disappear. This tests if big delays help or hurt.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_BIG_DELAYS_SCRIPT],
    )

    # Longer timeout for slow server
    with anyio.fail_after(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("slow_tool", arguments={})
                assert result.content[0].text == "Slow result after 3 seconds"


# Server that sends multiple responses rapidly
SERVER_BURST_RESPONSES_SCRIPT = textwrap.dedent("""
    import json
    import sys

    def send_response(response):
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}, "logging": {}},
                        "serverInfo": {"name": "burst-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "burst_tool",
                            "description": "Burst tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # Send many log notifications in rapid burst BEFORE response
                # This tests if the client can handle rapid incoming messages
                for i in range(20):
                    send_response({
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {
                            "level": "info",
                            "data": f"Burst log {i}"
                        }
                    })

                # Then send the actual response
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Result after burst"}],
                        "isError": False
                    }
                })

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_server_burst_responses():
    """
    Test server that sends many messages in rapid succession.

    This tests if the 0-capacity streams can handle burst traffic
    without deadlocking.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_BURST_RESPONSES_SCRIPT],
    )

    log_count = 0

    async def log_callback(params):
        nonlocal log_count
        log_count += 1

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, logging_callback=log_callback) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("burst_tool", arguments={})
                assert result.content[0].text == "Result after burst"

    # All 20 log messages should have been received
    assert log_count == 20


# Test with a slow message handler that blocks processing
@pytest.mark.anyio
async def test_slow_message_handler():
    """
    Test with a message handler that takes a long time.

    If the message handler blocks, it could prevent the receive loop
    from processing responses, causing a hang.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    handler_calls = 0

    async def slow_message_handler(message):
        nonlocal handler_calls
        handler_calls += 1
        # Simulate slow processing
        await anyio.sleep(0.5)

    with anyio.fail_after(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, message_handler=slow_message_handler) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("echo", arguments={})
                assert result.content[0].text == "Hello from tool"


# Test with slow logging callback
@pytest.mark.anyio
async def test_slow_logging_callback():
    """
    Test with a logging callback that blocks.

    This could cause the receive loop to block, preventing
    tool call responses from being processed.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_WITH_LOGS_SCRIPT],
    )

    log_calls = 0

    async def slow_log_callback(params):
        nonlocal log_calls
        log_calls += 1
        # Simulate slow logging (e.g., writing to slow disk, network logging)
        await anyio.sleep(1.0)

    with anyio.fail_after(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, logging_callback=slow_log_callback) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("log_tool", arguments={})
                assert result.content[0].text == "Done with logs"

    assert log_calls == 3


# Test many rapid iterations to catch intermittent issues
@pytest.mark.anyio
async def test_many_rapid_iterations():
    """
    Run many rapid iterations to catch timing-sensitive issues.

    The original issue may be intermittent, so we need many tries.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    success_count = 0
    iterations = 50

    for i in range(iterations):
        try:
            with anyio.fail_after(5):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await session.list_tools()
                        result = await session.call_tool("echo", arguments={})
                        if result.content[0].text == "Hello from tool":
                            success_count += 1
        except TimeoutError:
            # This would indicate the hang is reproduced!
            pass

    # All iterations should succeed
    assert success_count == iterations, f"Only {success_count}/{iterations} succeeded - issue may be reproduced!"


# Test with a server that closes stdout abruptly
SERVER_ABRUPT_CLOSE_SCRIPT = textwrap.dedent("""
    import json
    import sys

    def send_response(response):
        print(json.dumps(response), flush=True)

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    tool_calls = 0

    def main():
        global tool_calls

        while True:
            request = read_request()
            if request is None:
                break

            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "abrupt-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "abrupt_tool",
                            "description": "Tool that causes abrupt close",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                tool_calls += 1
                if tool_calls >= 2:
                    # On second call, send response then exit abruptly
                    send_response({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": "Goodbye!"}],
                            "isError": False
                        }
                    })
                    sys.exit(0)
                else:
                    send_response({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": "First call OK"}],
                            "isError": False
                        }
                    })

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_server_abrupt_exit():
    """
    Test behavior when server exits abruptly after sending response.

    This tests if the client handles server exit gracefully.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_ABRUPT_CLOSE_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                # First call should work
                result = await session.call_tool("abrupt_tool", arguments={})
                assert result.content[0].text == "First call OK"

                # Second call - server will exit after this
                result = await session.call_tool("abrupt_tool", arguments={})
                assert result.content[0].text == "Goodbye!"


# =============================================================================
# EXTREME TIMING TESTS - Trying to exploit race conditions
# =============================================================================


# Server that responds BEFORE reading full request (simulating race)
SERVER_PREEMPTIVE_RESPONSE_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import os

    # Make stdout unbuffered
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

    def send_response(response):
        sys.stdout.write(json.dumps(response) + '\\n')
        sys.stdout.flush()

    def read_request():
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        request_count = 0
        while True:
            request = read_request()
            if request is None:
                break

            request_count += 1
            method = request.get("method", "")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "preemptive-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "race_tool",
                            "description": "Race tool",
                            "inputSchema": {"type": "object", "properties": {}}
                        }]
                    }
                })
            elif method == "tools/call":
                # Immediately respond - no processing
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Preemptive result"}],
                        "isError": False
                    }
                })
            elif method == "ping":
                send_response({"jsonrpc": "2.0", "id": request_id, "result": {}})

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_preemptive_server_response():
    """
    Test with a server that uses unbuffered output and responds immediately.

    This maximizes the chance of responses arriving before client is ready.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-c", SERVER_PREEMPTIVE_RESPONSE_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("race_tool", arguments={})
                assert result.content[0].text == "Preemptive result"


@pytest.mark.anyio
async def test_rapid_initialize_list_call_sequence():
    """
    Test rapid sequence with no delays between operations.

    The original issue might be triggered by specific operation sequences.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-c", MINIMAL_SERVER_SCRIPT],
    )

    for _ in range(10):
        with anyio.fail_after(5):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    # No awaits between these - maximize race condition chance
                    init_task = session.initialize()
                    await init_task

                    list_task = session.list_tools()
                    await list_task

                    call_task = session.call_tool("echo", arguments={})
                    result = await call_task

                    assert result.content[0].text == "Hello from tool"


@pytest.mark.anyio
async def test_immediate_tool_call_after_initialize():
    """
    Test calling tool immediately after initialize (no list_tools).

    This tests a different code path that might have different timing.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Skip list_tools, go straight to call_tool
                result = await session.call_tool("echo", arguments={})
                assert result.content[0].text == "Hello from tool"


# Server with explicit pipe buffering disabled
SERVER_NO_BUFFERING_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import os

    # Disable all buffering
    os.environ['PYTHONUNBUFFERED'] = '1'
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
    sys.stdin = os.fdopen(sys.stdin.fileno(), 'r', buffering=1)

    def main():
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)
                method = request.get("method", "")
                request_id = request.get("id")

                response = None
                if method == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "unbuffered-server", "version": "1.0"}
                        }
                    }
                elif method == "notifications/initialized":
                    continue
                elif method == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "tools": [{
                                "name": "unbuffered_tool",
                                "description": "Unbuffered tool",
                                "inputSchema": {"type": "object", "properties": {}}
                            }]
                        }
                    }
                elif method == "tools/call":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": "Unbuffered result"}],
                            "isError": False
                        }
                    }
                elif method == "ping":
                    response = {"jsonrpc": "2.0", "id": request_id, "result": {}}
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Unknown: {method}"}
                    }

                if response:
                    sys.stdout.write(json.dumps(response) + '\\n')
                    sys.stdout.flush()
            except Exception:
                break

    if __name__ == "__main__":
        main()
""").strip()


@pytest.mark.anyio
async def test_fully_unbuffered_server():
    """
    Test with a server that has all buffering disabled.

    This might expose issues with pipe buffering on different platforms.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-c", SERVER_NO_BUFFERING_SCRIPT],
        env={"PYTHONUNBUFFERED": "1"},
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert len(tools.tools) == 1

                result = await session.call_tool("unbuffered_tool", arguments={})
                assert result.content[0].text == "Unbuffered result"


@pytest.mark.anyio
async def test_concurrent_sessions_to_same_server_type():
    """
    Test running multiple sessions concurrently to stress the system.

    This might expose resource contention or shared state issues.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    async def run_session(session_id: int):
        with anyio.fail_after(10):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
                    result = await session.call_tool("echo", arguments={})
                    assert result.content[0].text == "Hello from tool"
                    return session_id

    results = []
    async with anyio.create_task_group() as tg:
        for i in range(10):

            async def wrapper(sid: int = i):
                results.append(await run_session(sid))

            tg.start_soon(wrapper)

    assert len(results) == 10


@pytest.mark.anyio
async def test_stress_many_sequential_sessions():
    """
    Stress test: create many sequential sessions.

    This tests if there are any resource leaks or state issues across sessions.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    for _ in range(30):
        with anyio.fail_after(5):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
                    result = await session.call_tool("echo", arguments={})
                    assert result.content[0].text == "Hello from tool"


# =============================================================================
# PATCHED SDK TESTS - Add delays in the SDK to trigger race conditions
# =============================================================================


@pytest.mark.anyio
async def test_with_receive_loop_delay():
    """
    Test by delaying the receive loop start.

    If there's a race between sending requests and the receive loop being ready,
    this should trigger it.
    """
    import mcp.shared.session as session_module

    original_enter = session_module.BaseSession.__aenter__

    async def patched_enter(self):
        result = await original_enter(self)
        # Add delay AFTER _receive_loop is started with start_soon
        # This gives time for requests to be sent before loop is ready
        await anyio.sleep(0.01)
        return result

    session_module.BaseSession.__aenter__ = patched_enter

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", MINIMAL_SERVER_SCRIPT],
        )

        with anyio.fail_after(10):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
                    result = await session.call_tool("echo", arguments={})
                    assert result.content[0].text == "Hello from tool"
    finally:
        session_module.BaseSession.__aenter__ = original_enter


@pytest.mark.anyio
async def test_with_send_delay():
    """
    Test by delaying message sends.

    This might trigger race conditions between send and receive.
    """
    import mcp.shared.session as session_module

    original_send = session_module.BaseSession.send_request

    async def patched_send(self, request, result_type, **kwargs):
        await anyio.sleep(0.001)  # Tiny delay before sending
        return await original_send(self, request, result_type, **kwargs)

    session_module.BaseSession.send_request = patched_send

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", MINIMAL_SERVER_SCRIPT],
        )

        with anyio.fail_after(10):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()
                    result = await session.call_tool("echo", arguments={})
                    assert result.content[0].text == "Hello from tool"
    finally:
        session_module.BaseSession.send_request = original_send


# Test that tries to trigger the issue by NOT waiting for initialization
@pytest.mark.anyio
async def test_operations_without_awaiting_previous():
    """
    Test starting operations before previous ones complete.

    This might expose race conditions in request handling.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                # Start initialize
                init_result = await session.initialize()
                assert init_result is not None

                # Create tasks for list_tools and call_tool and start them nearly simultaneously
                async with anyio.create_task_group() as tg:
                    list_result = [None]
                    call_result = [None]

                    async def do_list():
                        list_result[0] = await session.list_tools()

                    async def do_call():
                        # Small delay to ensure list starts first
                        await anyio.sleep(0.001)
                        call_result[0] = await session.call_tool("echo", arguments={})

                    tg.start_soon(do_list)
                    tg.start_soon(do_call)

                assert list_result[0] is not None
                assert call_result[0] is not None
                assert call_result[0].content[0].text == "Hello from tool"


# Test with artificial CPU pressure
@pytest.mark.anyio
async def test_with_cpu_pressure():
    """
    Test with CPU pressure from concurrent computation.

    This might expose timing issues that are masked when the system is idle.
    """
    import threading
    import time

    stop_event = threading.Event()

    def cpu_pressure():
        """Generate CPU pressure in a background thread."""
        while not stop_event.is_set():
            # Busy loop
            sum(range(10000))
            time.sleep(0.0001)

    # Start pressure threads
    threads = [threading.Thread(target=cpu_pressure) for _ in range(4)]
    for t in threads:
        t.start()

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", MINIMAL_SERVER_SCRIPT],
        )

        # Run multiple iterations under CPU pressure
        for _ in range(10):
            with anyio.fail_after(10):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await session.list_tools()
                        result = await session.call_tool("echo", arguments={})
                        assert result.content[0].text == "Hello from tool"
    finally:
        stop_event.set()
        for t in threads:
            t.join()


# Test with uvloop if available (different event loop implementation)
@pytest.mark.anyio
async def test_basic_with_default_backend():
    """
    Basic test to confirm the default backend works.

    The issue might be specific to certain event loop implementations.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.list_tools()
                result = await session.call_tool("echo", arguments={})
                assert result.content[0].text == "Hello from tool"


# =============================================================================
# RAW SUBPROCESS TESTS - Direct control over pipe handling
# =============================================================================


@pytest.mark.anyio
async def test_raw_subprocess_communication():
    """
    Test using subprocess directly to verify MCP protocol works at low level.

    This bypasses the SDK's abstraction to test raw JSON-RPC communication.
    """
    import json
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", MINIMAL_SERVER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,  # Unbuffered
    )

    try:

        def send(msg):
            line = json.dumps(msg) + "\n"
            proc.stdin.write(line.encode())
            proc.stdin.flush()

        def receive():
            line = proc.stdout.readline()
            if not line:
                return None
            return json.loads(line)

        # Initialize
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = receive()
        assert resp["id"] == 1
        assert "result" in resp

        # Send initialized notification
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # List tools
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        resp = receive()
        assert resp["id"] == 2
        assert len(resp["result"]["tools"]) == 1

        # Call tool - this is where issue #262 hangs
        send({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {}},
        })
        resp = receive()
        assert resp["id"] == 3
        assert resp["result"]["content"][0]["text"] == "Hello from tool"

    finally:
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        proc.terminate()
        proc.wait()


@pytest.mark.anyio
async def test_raw_subprocess_rapid_calls():
    """
    Test rapid tool calls using raw subprocess.

    Eliminates SDK overhead to test if the issue is in the SDK layer.
    """
    import json
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", MINIMAL_SERVER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    try:

        def send(msg):
            line = json.dumps(msg) + "\n"
            proc.stdin.write(line.encode())
            proc.stdin.flush()

        def receive():
            line = proc.stdout.readline()
            if not line:
                return None
            return json.loads(line)

        # Initialize
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        receive()
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # List tools
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        receive()

        # Rapid tool calls
        for i in range(20):
            send({
                "jsonrpc": "2.0",
                "id": 10 + i,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {}},
            })
            resp = receive()
            assert resp["id"] == 10 + i
            assert resp["result"]["content"][0]["text"] == "Hello from tool"

    finally:
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
        proc.terminate()
        proc.wait()


@pytest.mark.anyio
async def test_with_process_priority():
    """
    Test with modified process priority.

    WSL might handle process scheduling differently, so priority changes
    might expose timing issues.
    """
    import os

    # Try to lower our priority to make subprocess faster relative to us
    try:
        os.nice(5)  # Increase niceness (lower priority)
    except (OSError, PermissionError):
        pass  # Ignore if we can't change priority

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", MINIMAL_SERVER_SCRIPT],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.list_tools()
                result = await session.call_tool("echo", arguments={})
                assert result.content[0].text == "Hello from tool"
