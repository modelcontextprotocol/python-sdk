"""A streamable-HTTP obligation that the stream-driver work must not break.

The request-coroutine orphan. A cancelled request no longer receives the
`{"code":0,"message":"Request cancelled"}` frame the JSON-RPC dispatcher used to write, so
the legacy streamable-HTTP JSON-response-mode POST loop must not wait for an answer to the
cancelled request that never comes (which would leave the POST coroutine and its
`_request_streams` entry lingering until the client disconnects). This module cancels an
in-flight request over legacy HTTP JSON mode and requires that the POST completes, its
stream entry is released, and the session keeps serving. The transport closes the
cancelled request's response stream; the dispatcher writes nothing for the id.

Everything runs in process: `StreamableHTTPSessionManager` mounted in Starlette, an httpx2
client on the suite's streaming ASGI bridge, raw JSON-RPC over HTTP - because the properties
under test (a POST's completion, a stream table, statuses) are things the high-level client
cannot observe.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx2
import pytest
from mcp_types import CallToolRequestParams, CallToolResult, TextContent
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from tests.interaction.transports import StreamingASGITransport

pytestmark = pytest.mark.anyio

Ctx = ServerRequestContext[dict[str, Any], Any]

# The in-process app is mounted at this origin purely so URLs are well-formed.
BASE_URL = "http://127.0.0.1:8000"

JSON_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@dataclass
class Probe:
    """Per-test observation points; created inside the running backend."""

    entered: anyio.Event = field(default_factory=anyio.Event)
    """The `slow` tool handler has started: the request is genuinely in flight."""

    release: anyio.Event = field(default_factory=anyio.Event)
    """Lets a parked `slow` call return; the peer-cancelled one never gets here."""


def tool_handler(probe: Probe) -> Callable[[Ctx, CallToolRequestParams], Awaitable[CallToolResult]]:
    """The suite's `tools/call` handler: `slow` parks on the probe, anything else returns
    immediately."""

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "slow":
            probe.entered.set()
            await probe.release.wait()
        return CallToolResult(content=[TextContent(type="text", text=f"{params.name} done")])

    return call_tool


def make_server(probe: Probe) -> Server[dict[str, Any]]:
    """A dual-era lowlevel server exposing the probe-driven tool."""
    return Server("http-orphan", version="0.0.0", on_call_tool=tool_handler(probe))


@asynccontextmanager
async def running_app(
    server: Server[dict[str, Any]], *, json_response: bool
) -> AsyncIterator[tuple[Starlette, StreamableHTTPSessionManager]]:
    """Serve `server`'s streamable-HTTP surface in process; yield the ASGI app and its manager."""
    # DNS-rebinding protection guards a network path an in-process app does not have.
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=json_response,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = Starlette(routes=[Mount("/mcp", app=manager.handle_request)])
    async with manager.run():
        yield app, manager


def http_client(app: Starlette) -> httpx2.AsyncClient:
    """An httpx2 client served in process by `app` (a Mount 307-redirects the bare path)."""
    return httpx2.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL, follow_redirects=True)


async def legacy_handshake(client: httpx2.AsyncClient) -> dict[str, str]:
    """Open a 2025-era session over streamable HTTP; return the headers that address it."""
    init = await client.post(
        "/mcp",
        headers=JSON_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_HANDSHAKE_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "http-suite", "version": "0"},
            },
        },
    )
    assert init.status_code == 200, f"handshake failed: {init.status_code} {init.text}"
    session_headers = {
        **JSON_HEADERS,
        MCP_SESSION_ID_HEADER: init.headers[MCP_SESSION_ID_HEADER],
        MCP_PROTOCOL_VERSION_HEADER: init.json()["result"]["protocolVersion"],
    }
    initialized = await client.post(
        "/mcp", headers=session_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert initialized.status_code == 202, f"initialized notification refused: {initialized.status_code}"
    return session_headers


def open_request_streams(manager: StreamableHTTPSessionManager) -> set[str]:
    """The per-request response streams the legacy transport still holds open.

    Private state by necessity: the orphan IS a stream-table entry that outlives its POST,
    which nothing on the public surface exposes.
    """
    open_keys: set[str] = set()
    for transport in manager._server_instances.values():
        open_keys.update(str(key) for key in transport._request_streams)
    return open_keys


async def test_peer_cancel_in_legacy_json_mode_completes_the_post_and_releases_its_stream() -> None:
    """Legacy streamable HTTP, JSON-response mode: the peer cancels an in-flight
    `tools/call` with `notifications/cancelled`. The POST awaiting that call MUST complete,
    its `_request_streams` entry MUST be released, and the session MUST keep serving - all
    without a resurrected dispatcher cancel frame. A peer cancel is also not a server fault,
    so the completed POST must not be a 5xx.

    Steps: handshake; POST a slow tool call in the background and wait until it is in
    flight (its stream entry exists); POST the cancel; note whether the pending POST
    finished within the bound and whether its stream entry is gone; make a follow-up call to
    prove the session still serves. Observations are gathered on the connection and
    asserted after it closes, so a failure reads as the assertion, not the bridge's group.
    """
    probe = Probe()
    server = make_server(probe)
    outcome: dict[str, httpx2.Response] = {}
    call_returned = anyio.Event()
    in_flight_stream_seen = completed = False
    still_open: set[str] = set()
    async with running_app(server, json_response=True) as (app, manager), http_client(app) as client:
        session_headers = await legacy_handshake(client)

        async def post_the_slow_call() -> None:
            outcome["call"] = await client.post(
                "/mcp",
                headers=session_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-to-cancel",
                    "method": "tools/call",
                    "params": {"name": "slow", "arguments": {}},
                },
            )
            call_returned.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(post_the_slow_call)
            with anyio.fail_after(5):
                await probe.entered.wait()  # the call is in flight...
            # ...so its response stream exists; the release check below is not vacuous.
            in_flight_stream_seen = "call-to-cancel" in open_request_streams(manager)
            outcome["cancel_ack"] = await client.post(
                "/mcp",
                headers=session_headers,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": "call-to-cancel", "reason": "test"},
                },
            )
            with anyio.move_on_after(5):
                await call_returned.wait()
            completed = call_returned.is_set()
            still_open = open_request_streams(manager)
            # Tear down a POST that never returned so nothing else waits on the orphan.
            tg.cancel_scope.cancel()

        # The session is still alive: the same tool, released this time, is served.
        probe.release.set()
        followup = await client.post(
            "/mcp",
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "id": "call-followup",
                "method": "tools/call",
                "params": {"name": "fast", "arguments": {}},
            },
        )

    assert in_flight_stream_seen, (
        "no response stream was open for the in-flight request; if the legacy transport "
        "renamed its stream table, update `open_request_streams`"
    )
    assert outcome["cancel_ack"].status_code == 202, (
        f"the cancel notification must be accepted: {outcome['cancel_ack']}"
    )
    assert completed, (
        "the POST awaiting the peer-cancelled request never completed (orphaned request "
        f"coroutine, still pending 5s after the cancel); streams still open: {still_open}"
    )
    assert "call-to-cancel" not in still_open, (
        f"the cancelled request's response stream must be released, still open: {still_open}"
    )
    assert outcome["call"].status_code < 500, (
        f"a peer cancel is not a server fault, but the POST completed as {outcome['call'].status_code}: "
        f"{outcome['call'].text}"
    )
    assert followup.status_code == 200, f"the session must keep serving after a cancel: {followup.text}"
    assert followup.json()["result"]["content"][0]["text"] == "fast done"
