# Claude Debug
"""Test for HackerOne vulnerability report #3156202 - malformed input DOS."""

from typing import Any

import anyio
import pytest

from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.types import (
    INVALID_PARAMS,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    ServerCapabilities,
)


@pytest.mark.anyio
async def test_malformed_initialize_request_does_not_crash_server():
    """
    Test that malformed initialize requests return proper error responses
    instead of crashing the server (HackerOne #3156202).
    """
    # Create in-memory streams for testing
    read_send_stream, read_receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send_stream, write_receive_stream = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        # Create a malformed initialize request (missing required params field)
        malformed_request = JSONRPCRequest(
            jsonrpc="2.0",
            id="f20fe86132ed4cd197f89a7134de5685",
            method="initialize",
            # params=None  # Missing required params field
        )

        # Wrap in session message
        request_message = SessionMessage(message=JSONRPCMessage(malformed_request))

        # Start a server session
        async with ServerSession(
            read_stream=read_receive_stream,
            write_stream=write_send_stream,
            init_options=InitializationOptions(
                server_name="test_server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ):
            # Send the malformed request
            await read_send_stream.send(request_message)

            # Give the session time to process the request
            await anyio.sleep(0.1)

            # Check that we received an error response instead of a crash
            try:
                response_message = write_receive_stream.receive_nowait()
                response = response_message.message.root

                # Verify it's a proper JSON-RPC error response
                assert isinstance(response, JSONRPCError)
                assert response.jsonrpc == "2.0"
                assert response.id == "f20fe86132ed4cd197f89a7134de5685"
                assert response.error.code == INVALID_PARAMS
                assert "Invalid request parameters" in response.error.message

                # Verify the session is still alive and can handle more requests
                # Send another malformed request to confirm server stability
                another_malformed_request = JSONRPCRequest(
                    jsonrpc="2.0",
                    id="test_id_2",
                    method="tools/call",
                    # params=None  # Missing required params
                )
                another_request_message = SessionMessage(message=JSONRPCMessage(another_malformed_request))

                await read_send_stream.send(another_request_message)
                await anyio.sleep(0.1)

                # Should get another error response, not a crash
                second_response_message = write_receive_stream.receive_nowait()
                second_response = second_response_message.message.root

                assert isinstance(second_response, JSONRPCError)
                assert second_response.id == "test_id_2"
                assert second_response.error.code == INVALID_PARAMS

            except anyio.WouldBlock:
                pytest.fail("No response received - server likely crashed")
    finally:
        # Close all streams to ensure proper cleanup
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()


@pytest.mark.anyio
async def test_multiple_concurrent_malformed_requests():
    """
    Test that multiple concurrent malformed requests don't crash the server.
    """
    # Create in-memory streams for testing
    read_send_stream, read_receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](100)
    write_send_stream, write_receive_stream = anyio.create_memory_object_stream[SessionMessage](100)

    try:
        # Start a server session
        async with ServerSession(
            read_stream=read_receive_stream,
            write_stream=write_send_stream,
            init_options=InitializationOptions(
                server_name="test_server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ):
            # Send multiple malformed requests concurrently
            malformed_requests: list[SessionMessage] = []
            for i in range(10):
                malformed_request = JSONRPCRequest(
                    jsonrpc="2.0",
                    id=f"malformed_{i}",
                    method="initialize",
                    # params=None  # Missing required params
                )
                request_message = SessionMessage(message=JSONRPCMessage(malformed_request))
                malformed_requests.append(request_message)

            # Send all requests
            for request in malformed_requests:
                await read_send_stream.send(request)

            # Give time to process
            await anyio.sleep(0.2)

            # Verify we get error responses for all requests
            error_responses: list[Any] = []
            try:
                while True:
                    response_message = write_receive_stream.receive_nowait()
                    error_responses.append(response_message.message.root)
            except anyio.WouldBlock:
                pass  # No more messages

            # Should have received 10 error responses
            assert len(error_responses) == 10

            for i, response in enumerate(error_responses):
                assert isinstance(response, JSONRPCError)
                assert response.id == f"malformed_{i}"
                assert response.error.code == INVALID_PARAMS
    finally:
        # Close all streams to ensure proper cleanup
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()
