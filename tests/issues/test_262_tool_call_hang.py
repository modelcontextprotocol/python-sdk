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
