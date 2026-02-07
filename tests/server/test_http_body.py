from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.types import Message

from mcp.server.http_body import BodyTooLargeError, read_request_body


def make_request(*, body_chunks: list[bytes], headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }

    messages: list[Message] = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": i < len(body_chunks) - 1,
        }
        for i, chunk in enumerate(body_chunks)
    ]

    async def receive() -> Message:
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


pytestmark = pytest.mark.anyio


async def test_read_request_body_allows_disabling_limit_with_none():
    request = make_request(body_chunks=[b"x" * 20])
    body = await read_request_body(request, max_body_bytes=None)
    assert body == b"x" * 20


async def test_read_request_body_rejects_non_positive_limit():
    request = make_request(body_chunks=[b"{}"])
    with pytest.raises(ValueError, match="max_body_bytes must be positive or None"):
        await read_request_body(request, max_body_bytes=0)


async def test_read_request_body_ignores_invalid_content_length_header():
    request = make_request(body_chunks=[b"{}"], headers={"content-length": "not-a-number"})
    body = await read_request_body(request, max_body_bytes=10)
    assert body == b"{}"


async def test_read_request_body_errors_if_more_chunks_arrive_after_limit_is_reached():
    # First chunk reaches the limit exactly; the next non-empty chunk should error.
    request = make_request(body_chunks=[b"12345", b"6"])
    with pytest.raises(BodyTooLargeError):
        await read_request_body(request, max_body_bytes=5)


async def test_read_request_body_handles_empty_request_body():
    request = make_request(body_chunks=[])
    body = await read_request_body(request, max_body_bytes=10)
    assert body == b""
