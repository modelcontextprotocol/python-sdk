"""Test for issue #1561: unknown methods should return METHOD_NOT_FOUND."""

import anyio
import pytest

from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.types import METHOD_NOT_FOUND, JSONRPCError, JSONRPCRequest, ServerCapabilities


@pytest.mark.anyio
async def test_invalid_method_returns_method_not_found() -> None:
    read_send_stream, read_receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send_stream, write_receive_stream = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        async with ServerSession(
            read_stream=read_receive_stream,
            write_stream=write_send_stream,
            init_options=InitializationOptions(
                server_name="test_server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ):
            await read_send_stream.send(
                SessionMessage(
                    message=JSONRPCRequest(
                        jsonrpc="2.0",
                        id=1,
                        method="invalid/method",
                        params={},
                    )
                )
            )

            await anyio.sleep(0.1)

            response_message = write_receive_stream.receive_nowait()
            response = response_message.message

            assert isinstance(response, JSONRPCError)
            assert response.id == 1
            assert response.error.code == METHOD_NOT_FOUND
            assert response.error.message == "Method not found"
    finally:  # pragma: no cover
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()
