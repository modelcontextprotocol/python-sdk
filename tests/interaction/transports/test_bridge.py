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

    async with (
        httpx.AsyncClient(transport=StreamingASGITransport(chunked_app), base_url="http://bridge") as http,
        http.stream("GET", "/chunks") as response,
    ):
        with anyio.fail_after(5):
            chunks = [chunk async for chunk in response.aiter_raw()]

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain"
    assert chunks == [b"first", b"second"]


async def test_a_second_response_after_the_first_completes_is_invisible_to_the_client() -> None:
    """Only the first complete response reaches the client; a trailing start/body pair is dropped.

    Starlette's `request_response` produces exactly this sequence when an endpoint's
    sub-application has already sent a complete rejection response (the legacy SSE transport's
    request validation): the endpoint still returns a `Response`, which sends a second response.
    """

    async def double_responding_app(scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"
        assert (await receive())["type"] == "http.request"
        await send({"type": "http.response.start", "status": 421, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"rejected", "more_body": False})
        await send({"type": "http.response.start", "status": 200, "headers": [(b"x-late", b"yes")]})
        await send({"type": "http.response.body", "body": b"too late", "more_body": False})

    transport = StreamingASGITransport(double_responding_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as http:
        response = await http.get("/double")

    assert response.status_code == 421
    assert response.text == "rejected"
    assert "x-late" not in response.headers


async def test_body_chunks_after_the_final_chunk_are_ignored() -> None:
    """Extra body chunks after `more_body: False` neither reach the client nor fail the application."""
    application_finished = anyio.Event()

    async def overflowing_app(scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"
        assert (await receive())["type"] == "http.request"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"complete", "more_body": False})
        await send({"type": "http.response.body", "body": b"overflow", "more_body": True})
        application_finished.set()

    transport = StreamingASGITransport(overflowing_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as http:
        response = await http.get("/overflow")
        with anyio.fail_after(5):
            await application_finished.wait()

    assert response.status_code == 200
    assert response.text == "complete"


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


async def test_disabling_cancel_on_close_lets_the_application_finish_after_disconnect() -> None:
    """With cancel_on_close=False, an application that runs cleanup after seeing http.disconnect
    completes that cleanup before the transport finishes closing."""
    cleanup_ran = anyio.Event()

    async def lingering_app(scope: Scope, receive: Receive, send: Send) -> None:
        assert scope["type"] == "http"
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        assert (await receive())["type"] == "http.disconnect"
        cleanup_ran.set()

    transport = StreamingASGITransport(lingering_app, cancel_on_close=False)
    with anyio.fail_after(5):
        async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as http:
            async with http.stream("GET", "/linger") as response:
                assert response.status_code == 200
            assert not cleanup_ran.is_set()
    assert cleanup_ran.is_set()
