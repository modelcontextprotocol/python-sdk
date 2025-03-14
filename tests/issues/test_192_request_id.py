import anyio
import pytest

from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    NotificationParams,
)


@pytest.mark.anyio
async def test_request_id_match() -> None:
    """Test that the server preserves request IDs in responses."""
    server = Server("test")
    custom_request_id = "test-123"

    # Create memory streams for communication
    client_writer, client_reader = anyio.create_memory_object_stream(1)
    server_writer, server_reader = anyio.create_memory_object_stream(1)

    # Server task to process the request
    async def run_server():
        async with client_reader, server_writer:
            await server.run(
                client_reader,
                server_writer,
                InitializationOptions(
                    server_name="test",
                    server_version="1.0.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
                raise_exceptions=True,
            )

    # Start server task
    async with (
        anyio.create_task_group() as tg,
        client_writer,
        client_reader,
        server_writer,
        server_reader,
    ):
        tg.start_soon(run_server)

        # Send initialize request
        init_req = JSONRPCRequest(
            id="init-1",
            method="initialize",
            params=InitializeRequestParams(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ClientCapabilities(),
                clientInfo=Implementation(name="test-client", version="1.0.0"),
            ).model_dump(by_alias=True, exclude_none=True),
            jsonrpc="2.0",
        )

        await client_writer.send(JSONRPCMessage(root=init_req))
        await server_reader.receive()  # Get init response but don't need to check it

        # Send initialized notification
        initialized_notification = JSONRPCNotification(
            method="notifications/initialized",
            params=NotificationParams().model_dump(by_alias=True, exclude_none=True),
            jsonrpc="2.0",
        )
        await client_writer.send(JSONRPCMessage(root=initialized_notification))

        # Send ping request with custom ID
        ping_request = JSONRPCRequest(
            id=custom_request_id, method="ping", params={}, jsonrpc="2.0"
        )

        await client_writer.send(JSONRPCMessage(root=ping_request))

        # Read response
        response = await server_reader.receive()

        # Verify response ID matches request ID
        assert (
            response.root.id == custom_request_id
        ), "Response ID should match request ID"

        # Cancel server task
        tg.cancel_scope.cancel()
