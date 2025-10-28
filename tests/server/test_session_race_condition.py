"""
Test for race condition fix in initialization flow.

This test verifies that requests can be processed immediately after
responding to InitializeRequest, without waiting for InitializedNotification.

This is critical for HTTP transport where requests can arrive in any order.
"""

import anyio
import pytest

import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import ServerCapabilities, Tool


@pytest.mark.anyio
async def test_request_immediately_after_initialize_response():
    """
    Test that requests are accepted immediately after initialize response.

    This reproduces the race condition in stateful HTTP mode where:
    1. Client sends InitializeRequest
    2. Server responds with InitializeResult
    3. Client immediately sends tools/list (before server receives InitializedNotification)
    4. Without fix: Server rejects with "Received request before initialization was complete"
    5. With fix: Server accepts and processes the request

    This test simulates the HTTP transport behavior where InitializedNotification
    may arrive in a separate POST request after other requests.
    """
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](10)

    tools_list_success = False
    error_received = None

    async def run_server():
        nonlocal tools_list_success

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

                # Handle tools/list request
                if isinstance(message, RequestResponder):
                    if isinstance(message.request.root, types.ListToolsRequest):
                        tools_list_success = True
                        # Respond with a tool list
                        with message:
                            await message.respond(
                                types.ServerResult(
                                    types.ListToolsResult(
                                        tools=[
                                            Tool(
                                                name="example_tool",
                                                description="An example tool",
                                                inputSchema={"type": "object", "properties": {}},
                                            )
                                        ]
                                    )
                                )
                            )

                # Handle InitializedNotification
                if isinstance(message, types.ClientNotification):
                    if isinstance(message.root, types.InitializedNotification):
                        # Done - exit gracefully
                        return

    async def mock_client():
        nonlocal error_received

        # Step 1: Send InitializeRequest
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCRequest(
                        jsonrpc="2.0",
                        id=1,
                        method="initialize",
                        params=types.InitializeRequestParams(
                            protocolVersion=types.LATEST_PROTOCOL_VERSION,
                            capabilities=types.ClientCapabilities(),
                            clientInfo=types.Implementation(name="test-client", version="1.0.0"),
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Step 2: Wait for InitializeResult
        init_msg = await server_to_client_receive.receive()
        assert isinstance(init_msg.message.root, types.JSONRPCResponse)

        # Step 3: Immediately send tools/list BEFORE InitializedNotification
        # This is the race condition scenario
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCRequest(
                        jsonrpc="2.0",
                        id=2,
                        method="tools/list",
                    )
                )
            )
        )

        # Step 4: Check the response
        tools_msg = await server_to_client_receive.receive()
        if isinstance(tools_msg.message.root, types.JSONRPCError):
            error_received = tools_msg.message.root.error.message

        # Step 5: Send InitializedNotification
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCNotification(
                        jsonrpc="2.0",
                        method="notifications/initialized",
                    )
                )
            )
        )

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(run_server)
        tg.start_soon(mock_client)

    # With the PR fix: tools_list_success should be True, error_received should be None
    # Without the fix: error_received would contain "Received request before initialization was complete"
    assert tools_list_success, f"tools/list should have succeeded. Error received: {error_received}"
    assert error_received is None, f"Expected no error, but got: {error_received}"
