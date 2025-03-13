from types import NoneType

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientNotification,
    ClientRequest,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    MessageFrame,
    ServerCapabilities,
    ServerResult,
)


@pytest.mark.anyio
async def test_client_session_initialize():
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        MessageFrame[NoneType]
    ](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        MessageFrame[NoneType]
    ](1)

    initialized_notification = None

    async def mock_server():
        nonlocal initialized_notification

        jsonrpc_request = await client_to_server_receive.receive()
        assert isinstance(jsonrpc_request, MessageFrame)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(
                    logging=None,
                    resources=None,
                    tools=None,
                    experimental=None,
                    prompts=None,
                ),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                instructions="The server instructions.",
            )
        )

        async with server_to_client_send:
            assert isinstance(jsonrpc_request.message.root, JSONRPCRequest)
            await server_to_client_send.send(
                MessageFrame(
                    message=JSONRPCMessage(
                        JSONRPCResponse(
                            jsonrpc="2.0",
                            id=jsonrpc_request.message.root.id,
                            result=result.model_dump(
                                by_alias=True, mode="json", exclude_none=True
                            ),
                        )
                    ),
                    raw=None,
                )
            )
            jsonrpc_notification = await client_to_server_receive.receive()
            assert isinstance(jsonrpc_notification.message, JSONRPCMessage)
            initialized_notification = ClientNotification.model_validate(
                jsonrpc_notification.message.model_dump(
                    by_alias=True, mode="json", exclude_none=True
                )
            )

    async def listen_session():
        async for message in session.incoming_messages:
            if isinstance(message, Exception):
                raise message

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        tg.start_soon(listen_session)
        result = await session.initialize()

    # Assert the result
    assert isinstance(result, InitializeResult)
    assert result.protocolVersion == LATEST_PROTOCOL_VERSION
    assert isinstance(result.capabilities, ServerCapabilities)
    assert result.serverInfo == Implementation(name="mock-server", version="0.1.0")
    assert result.instructions == "The server instructions."

    # Check that the client sent the initialized notification
    assert initialized_notification
    assert isinstance(initialized_notification.root, InitializedNotification)
