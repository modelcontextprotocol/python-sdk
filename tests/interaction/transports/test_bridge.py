"""Contract tests for the suite's streaming ASGI bridge.

These pin what `StreamingASGITransport` itself guarantees — chunk-by-chunk delivery, disconnect
propagation, and failure handling — against minimal hand-written ASGI applications, so the MCP
transport tests built on top of it never have to wonder what the harness provides. They are
harness self-tests, not interaction-model tests, and are exempted from the requirement-coverage
contract in `test_coverage.py`.
"""

import anyio
import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from tests.interaction.transports._bridge import StreamingASGITransport

pytestmark = pytest.mark.anyio


async def test_response_chunks_arrive_as_the_application_sends_them() -> None:
    """Each body chunk is delivered as sent, empty chunks are skipped, and the stream ends with the application."""

    async def chunked_app(scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"
        assert (await receive())["type"] == "http.request"
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": True})
        await send({"type": "http.response.body", "body": b"second", "more_body": False})

    async with httpx.AsyncClient(transport=StreamingASGITransport(chunked_app), base_url="http://bridge") as http:
        async with http.stream("GET", "/chunks") as response:
            with anyio.fail_after(5):
                chunks = [chunk async for chunk in response.aiter_raw()]

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain"
    assert chunks == [b"first", b"second"]


async def test_closing_the_response_delivers_a_disconnect_to_the_application() -> None:
    """A client that closes the response early is seen by the application as an http.disconnect."""
    seen_after_request: list[Message] = []
    disconnect_seen = anyio.Event()

    async def waiting_app(scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"
        assert (await receive())["type"] == "http.request"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        seen_after_request.append(await receive())
        disconnect_seen.set()

    async with httpx.AsyncClient(transport=StreamingASGITransport(waiting_app), base_url="http://bridge") as http:
        async with http.stream("GET", "/wait") as response:
            assert response.status_code == 200
        # Leaving the stream block closes the response while the application is still mid-response.
        with anyio.fail_after(5):
            await disconnect_seen.wait()

    assert seen_after_request == [{"type": "http.disconnect"}]


async def test_an_application_failure_before_the_response_starts_fails_the_request() -> None:
    """An exception raised before http.response.start reaches the caller as that same exception."""

    async def broken_app(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("the demo application is broken")

    async with httpx.AsyncClient(transport=StreamingASGITransport(broken_app), base_url="http://bridge") as http:
        with pytest.raises(RuntimeError, match="the demo application is broken"):
            await http.get("/broken")
