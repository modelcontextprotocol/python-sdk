"""Harness self-tests pinning what `StreamingASGITransport` itself guarantees.

They cover chunk-by-chunk delivery, disconnect propagation, and failure handling. Not
interaction-model tests; exempted from the requirement-coverage contract in `test_coverage.py`.
"""

import anyio
import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from tests.interaction.transports._bridge import StreamingASGITransport

pytestmark = pytest.mark.anyio


async def test_response_chunks_arrive_as_the_application_sends_them() -> None:
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


async def test_closing_the_response_delivers_a_disconnect_to_the_application() -> None:
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
    async def broken_app(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("the demo application is broken")

    async with httpx.AsyncClient(transport=StreamingASGITransport(broken_app), base_url="http://bridge") as http:
        with pytest.raises(RuntimeError, match="the demo application is broken"):
            await http.get("/broken")


async def test_disabling_cancel_on_close_lets_the_application_finish_after_disconnect() -> None:
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
