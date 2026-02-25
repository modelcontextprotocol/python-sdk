import io
import sys

import anyio
import pytest

from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse, jsonrpc_message_adapter


@pytest.mark.anyio
async def test_stdio_server():
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
        JSONRPCResponse(jsonrpc="2.0", id=2, result={}),
    ]

    for message in messages:
        stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    async with stdio_server(stdin=anyio.AsyncFile(stdin), stdout=anyio.AsyncFile(stdout)) as (
        read_stream,
        write_stream,
    ):
        received_messages: list[JSONRPCMessage] = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):  # pragma: no cover
                    raise message
                received_messages.append(message.message)
                if len(received_messages) == 2:
                    break

        # Verify received messages
        assert len(received_messages) == 2
        assert received_messages[0] == JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        assert received_messages[1] == JSONRPCResponse(jsonrpc="2.0", id=2, result={})

        # Test sending responses from the server
        responses = [
            JSONRPCRequest(jsonrpc="2.0", id=3, method="ping"),
            JSONRPCResponse(jsonrpc="2.0", id=4, result={}),
        ]

        async with write_stream:
            for response in responses:
                session_message = SessionMessage(response)
                await write_stream.send(session_message)

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    received_responses = [jsonrpc_message_adapter.validate_json(line.strip()) for line in output_lines]
    assert len(received_responses) == 2
    assert received_responses[0] == JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
    assert received_responses[1] == JSONRPCResponse(jsonrpc="2.0", id=4, result={})


@pytest.mark.anyio
async def test_stdio_server_does_not_close_process_stdio(monkeypatch: pytest.MonkeyPatch):
    stdin_bytes = io.BytesIO()
    stdout_bytes = io.BytesIO()

    stdin_text = io.TextIOWrapper(stdin_bytes, encoding="utf-8")
    stdout_text = io.TextIOWrapper(stdout_bytes, encoding="utf-8")

    stdin_text.write(JSONRPCRequest(jsonrpc="2.0", id=1, method="ping").model_dump_json(by_alias=True) + "\n")
    stdin_text.seek(0)

    monkeypatch.setattr(sys, "stdin", stdin_text)
    monkeypatch.setattr(sys, "stdout", stdout_text)

    async with stdio_server() as (read_stream, write_stream):
        async with read_stream:
            first = await read_stream.receive()
            assert isinstance(first, SessionMessage)

        async with write_stream:
            await write_stream.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=2, result={})))

    # Regression check for #1933: process stdio should still be writable/readable.
    print("still-open")
    assert stdin_text.readable()
    assert stdout_text.writable()
