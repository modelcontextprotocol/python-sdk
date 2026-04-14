import anyio
import pytest

from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.types import INVALID_PARAMS, METHOD_NOT_FOUND, JSONRPCError, JSONRPCRequest, ServerCapabilities


@pytest.mark.anyio
async def test_invalid_method_names_return_method_not_found() -> None:
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
                    message=JSONRPCRequest(jsonrpc="2.0", id=1, method="invalid/method", params={})
                )
            )

            invalid_method_response = (await write_receive_stream.receive()).message

            assert isinstance(invalid_method_response, JSONRPCError)
            assert invalid_method_response.id == 1
            assert invalid_method_response.error.code == METHOD_NOT_FOUND
            assert invalid_method_response.error.message == "Method not found"

            await read_send_stream.send(
                SessionMessage(
                    message=JSONRPCRequest(jsonrpc="2.0", id=2, method="initialize")
                )
            )

            malformed_known_method_response = (await write_receive_stream.receive()).message

            assert isinstance(malformed_known_method_response, JSONRPCError)
            assert malformed_known_method_response.id == 2
            assert malformed_known_method_response.error.code == INVALID_PARAMS
            assert malformed_known_method_response.error.message == "Invalid request parameters"
    finally:  # pragma: lax no cover
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()
