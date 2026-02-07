from __future__ import annotations

from uuid import uuid4

import anyio
import pytest
from starlette.types import Message

from mcp.server.sse import SseServerTransport
from mcp.shared.message import SessionMessage


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

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}  # pragma: no cover

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
