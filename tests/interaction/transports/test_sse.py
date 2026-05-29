"""Behaviour specific to the legacy HTTP+SSE transport, exercised entirely in process.

Transport-agnostic behaviour is covered by the `connect`-fixture matrix, which runs the rest of
the suite over this transport as well; this file pins only what is observable on the SSE wiring
itself: the GET-then-POST connection lifecycle, the endpoint event, and how the message endpoint
rejects requests it cannot route to a session. Every test drives the server's real Starlette app
through the suite's streaming ASGI bridge.
"""

from uuid import UUID, uuid4

import anyio
import httpx
import pytest
from inline_snapshot import snapshot

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server import Server
from mcp.types import EmptyResult
from tests.interaction._connect import BASE_URL, build_sse_app
from tests.interaction._requirements import requirement
from tests.interaction.transports._bridge import StreamingASGITransport

pytestmark = pytest.mark.anyio


@requirement("transport:sse")
@requirement("transport:sse:endpoint-event")
async def test_endpoint_event_names_the_message_endpoint_with_a_fresh_session_id() -> None:
    """Connecting opens a GET stream whose first event names the POST endpoint and a fresh
    session id; messages POSTed there are answered on that stream, and disconnecting releases the
    server's session entry."""
    app, sse = build_sse_app(Server("legacy"))
    captured_session_id: list[str] = []

    def httpx_client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=StreamingASGITransport(app, cancel_on_close=False),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    with anyio.fail_after(5):
        async with sse_client(
            f"{BASE_URL}/sse", httpx_client_factory=httpx_client_factory, on_session_created=captured_session_id.append
        ) as (read, write):
            async with ClientSession(read, write) as client:  # pragma: no branch
                await client.initialize()
                assert len(captured_session_id) == 1
                assert UUID(hex=captured_session_id[0]) in sse._read_stream_writers
                assert await client.send_ping() == snapshot(EmptyResult())

    # `connect_sse` drops the session entry in a `finally` once the GET request has unwound; the
    # bridge lets that unwinding finish after the client has gone, so wait for the cleanup instead
    # of racing it. How many iterations that takes is a scheduling accident (usually zero), and on
    # 3.11 these post-unwind lines are invisible to the line tracer, hence the coverage exclusion.
    with anyio.fail_after(5):  # pragma: lax no cover
        while sse._read_stream_writers:
            await anyio.sleep(0.01)


@requirement("transport:sse:post:session-routing")
async def test_post_without_a_session_id_is_rejected() -> None:
    """A POST to the message endpoint with no session_id query parameter is answered 400."""
    app, _ = build_sse_app(Server("legacy"))
    async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http:
        response = await http.post("/messages/", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
    assert (response.status_code, response.text) == snapshot((400, "session_id is required"))


@requirement("transport:sse:post:session-routing")
async def test_post_with_a_malformed_session_id_is_rejected() -> None:
    """A POST whose session_id query parameter is not a UUID is answered 400."""
    app, _ = build_sse_app(Server("legacy"))
    async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http:
        response = await http.post(
            "/messages/", params={"session_id": "not-a-uuid"}, json={"jsonrpc": "2.0", "method": "ping", "id": 1}
        )
    assert (response.status_code, response.text) == snapshot((400, "Invalid session ID"))


@requirement("transport:sse:post:session-routing")
async def test_post_for_an_unknown_session_is_rejected() -> None:
    """A POST naming a well-formed session_id that no SSE stream owns is answered 404."""
    app, _ = build_sse_app(Server("legacy"))
    async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http:
        response = await http.post(
            "/messages/", params={"session_id": uuid4().hex}, json={"jsonrpc": "2.0", "method": "ping", "id": 1}
        )
    assert (response.status_code, response.text) == snapshot((404, "Could not find session"))
