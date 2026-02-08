from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import pytest
from pydantic import ValidationError
from starlette.responses import Response
from starlette.types import Message

from mcp.server.sse import SseServerTransport
from mcp.shared.message import SessionMessage


def make_receive(body: bytes) -> Callable[[], Awaitable[Message]]:
    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


@pytest.mark.anyio
async def test_sse_max_body_bytes_rejects_large_request():
    sse_transport = SseServerTransport("/messages/", max_body_bytes=10)

    session_id = uuid4()
    writer, reader = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    try:
        sse_transport._read_stream_writers[session_id] = writer

        sent_messages: list[Message] = []
        response_body = b""

        async def send(message: Message):
            nonlocal response_body
            sent_messages.append(message)
            if message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/messages/",
            "query_string": f"session_id={session_id.hex}".encode(),
            "headers": [(b"content-type", b"application/json")],
        }

        body = b'{"a":"' + (b"x" * 20) + b'"}'

        receive = make_receive(body)

        await sse_transport.handle_post_message(scope, receive, send)

        response_start = next(
            (msg for msg in sent_messages if msg["type"] == "http.response.start"),
            None,
        )
        assert response_start is not None, "Should have sent a response"
        assert response_start["status"] == 413
        assert response_body == b"Payload too large"
    finally:
        await writer.aclose()
        await reader.aclose()


@pytest.mark.anyio
async def test_sse_handle_post_message_short_circuits_on_security_error():
    sse_transport = SseServerTransport("/messages/")
    sse_transport._security.validate_request = AsyncMock(return_value=Response("blocked", status_code=403))  # type: ignore[method-assign]

    sent_messages: list[Message] = []
    response_body = b""

    async def send(message: Message):
        nonlocal response_body
        sent_messages.append(message)
        if message["type"] == "http.response.body":
            response_body += message.get("body", b"")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/messages/",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }
    receive = make_receive(b"{}")

    await sse_transport.handle_post_message(scope, receive, send)

    response_start = next((msg for msg in sent_messages if msg["type"] == "http.response.start"), None)
    assert response_start is not None, "Should have sent a response"
    assert response_start["status"] == 403
    assert response_body == b"blocked"


@pytest.mark.anyio
async def test_sse_handle_post_message_returns_400_when_session_id_missing():
    sse_transport = SseServerTransport("/messages/")

    sent_messages: list[Message] = []
    response_body = b""

    async def send(message: Message):
        nonlocal response_body
        sent_messages.append(message)
        if message["type"] == "http.response.body":
            response_body += message.get("body", b"")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/messages/",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }
    receive = make_receive(b"{}")

    await sse_transport.handle_post_message(scope, receive, send)

    response_start = next((msg for msg in sent_messages if msg["type"] == "http.response.start"), None)
    assert response_start is not None, "Should have sent a response"
    assert response_start["status"] == 400
    assert response_body == b"session_id is required"


@pytest.mark.anyio
async def test_sse_handle_post_message_returns_400_when_session_id_invalid():
    sse_transport = SseServerTransport("/messages/")

    sent_messages: list[Message] = []
    response_body = b""

    async def send(message: Message):
        nonlocal response_body
        sent_messages.append(message)
        if message["type"] == "http.response.body":
            response_body += message.get("body", b"")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/messages/",
        "query_string": b"session_id=not-a-uuid",
        "headers": [(b"content-type", b"application/json")],
    }
    receive = make_receive(b"{}")

    await sse_transport.handle_post_message(scope, receive, send)

    response_start = next((msg for msg in sent_messages if msg["type"] == "http.response.start"), None)
    assert response_start is not None, "Should have sent a response"
    assert response_start["status"] == 400
    assert response_body == b"Invalid session ID"


@pytest.mark.anyio
async def test_sse_handle_post_message_returns_404_when_session_not_found():
    sse_transport = SseServerTransport("/messages/")

    sent_messages: list[Message] = []
    response_body = b""

    async def send(message: Message):
        nonlocal response_body
        sent_messages.append(message)
        if message["type"] == "http.response.body":
            response_body += message.get("body", b"")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/messages/",
        "query_string": f"session_id={uuid4().hex}".encode(),
        "headers": [(b"content-type", b"application/json")],
    }
    receive = make_receive(b"{}")

    await sse_transport.handle_post_message(scope, receive, send)

    response_start = next((msg for msg in sent_messages if msg["type"] == "http.response.start"), None)
    assert response_start is not None, "Should have sent a response"
    assert response_start["status"] == 404
    assert response_body == b"Could not find session"


@pytest.mark.anyio
async def test_sse_handle_post_message_returns_400_and_sends_error_on_invalid_jsonrpc():
    sse_transport = SseServerTransport("/messages/", max_body_bytes=1_000)

    session_id = uuid4()
    writer, reader = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    try:
        sse_transport._read_stream_writers[session_id] = writer

        sent_messages: list[Message] = []
        response_body = b""

        async def send(message: Message):
            nonlocal response_body
            sent_messages.append(message)
            if message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/messages/",
            "query_string": f"session_id={session_id.hex}".encode(),
            "headers": [(b"content-type", b"application/json")],
        }
        receive = make_receive(b"{}")

        await sse_transport.handle_post_message(scope, receive, send)

        response_start = next((msg for msg in sent_messages if msg["type"] == "http.response.start"), None)
        assert response_start is not None, "Should have sent a response"
        assert response_start["status"] == 400
        assert response_body == b"Could not parse message"

        err = await reader.receive()
        assert isinstance(err, ValidationError)
    finally:
        await writer.aclose()
        await reader.aclose()


@pytest.mark.anyio
async def test_sse_handle_post_message_accepts_valid_jsonrpc_and_sends_session_message():
    sse_transport = SseServerTransport("/messages/", max_body_bytes=1_000)

    session_id = uuid4()
    writer, reader = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    try:
        sse_transport._read_stream_writers[session_id] = writer

        sent_messages: list[Message] = []
        response_body = b""

        async def send(message: Message):
            nonlocal response_body
            sent_messages.append(message)
            if message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/messages/",
            "query_string": f"session_id={session_id.hex}".encode(),
            "headers": [(b"content-type", b"application/json")],
        }

        body = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
        receive = make_receive(body)

        await sse_transport.handle_post_message(scope, receive, send)

        response_start = next((msg for msg in sent_messages if msg["type"] == "http.response.start"), None)
        assert response_start is not None, "Should have sent a response"
        assert response_start["status"] == 202
        assert response_body == b"Accepted"

        session_message = await reader.receive()
        assert isinstance(session_message, SessionMessage)
        assert getattr(session_message.message, "method", None) == "initialize"
    finally:
        await writer.aclose()
        await reader.aclose()
