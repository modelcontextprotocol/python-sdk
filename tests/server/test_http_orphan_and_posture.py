"""Two streamable-HTTP obligations that the stream-driver work must not break.

(i) The request-coroutine orphan. A cancelled request no longer receives the
`{"code":0,"message":"Request cancelled"}` frame the JSON-RPC dispatcher used to write, so
the legacy streamable-HTTP JSON-response-mode POST loop must not wait for an answer to the
cancelled request that never comes (which would leave the POST coroutine and its
`_request_streams` entry lingering until the client disconnects). This module cancels an
in-flight request over legacy HTTP JSON mode and requires that the POST completes, its
stream entry is released, and the session keeps serving. The transport closes the
cancelled request's response stream; the dispatcher writes nothing for the id.

(ii) Posture honoured over streamable HTTP. A `MODERN_ONLY` server refuses a 2025
`initialize` with -32022 whose data names the versions it serves; a `LEGACY_ONLY` server
refuses an enveloped modern request in its own (legacy) vocabulary instead of serving it.
`Server(posture=)` is one constructor property every transport reads; this file measures
the HTTP half of that claim.

Everything runs in process: `StreamableHTTPSessionManager` mounted in Starlette, an httpx2
client on the suite's streaming ASGI bridge, raw JSON-RPC over HTTP - because the properties
under test (a POST's completion, a stream table, statuses and error bodies) are things the
high-level client cannot observe.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx2
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    CallToolRequestParams,
    CallToolResult,
    TextContent,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Posture, Server, ServerRequestContext
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

# The modern per-request envelope for a request that claims the 2026 era over HTTP.
MODERN_ENVELOPE: dict[str, Any] = {
    PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
    CLIENT_INFO_META_KEY: {"name": "http-suite", "version": "0"},
    CLIENT_CAPABILITIES_META_KEY: {},
}


@dataclass
class Probe:
    """Per-test observation points; created inside the running backend."""

    entered: anyio.Event = field(default_factory=anyio.Event)
    """The `slow` tool handler has started: the request is genuinely in flight."""

    release: anyio.Event = field(default_factory=anyio.Event)
    """Lets a parked `slow` call return; the peer-cancelled one never gets here."""


def tool_handler(probe: Probe) -> Callable[[Ctx, CallToolRequestParams], Awaitable[CallToolResult]]:
    """One `tools/call` handler for every server in this file: `slow` parks on the probe,
    anything else returns immediately."""

    async def call_tool(ctx: Ctx, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "slow":
            probe.entered.set()
            await probe.release.wait()
        return CallToolResult(content=[TextContent(type="text", text=f"{params.name} done")])

    return call_tool


def make_server(probe: Probe) -> Server[dict[str, Any]]:
    """A dual-era lowlevel server (default posture) exposing the probe-driven tool."""
    return Server("http-orphan", version="0.0.0", on_call_tool=tool_handler(probe))


def make_postured_server(posture: Posture, probe: Probe) -> Server[dict[str, Any]]:
    """A lowlevel server declaring `posture`, over the same tool surface as `make_server`."""
    return Server("http-posture", version="0.0.0", posture=posture, on_call_tool=tool_handler(probe))


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


# --- (i) the request-coroutine orphan -----------------------------------------------------


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


# --- (ii) posture is honoured over streamable HTTP -----------------------------------------


async def test_modern_only_server_refuses_a_2025_handshake_over_http_with_the_version_error() -> None:
    """A server declared MODERN_ONLY refuses a 2025 `initialize` over streamable HTTP with
    -32022 whose data lists the versions it does serve - the modern era's own answer to a
    handshake attempt (versioning.mdx: a modern-only server SHOULD name its versions), not a
    legacy handshake completed by a transport that never read the posture."""
    server = make_postured_server(Posture.MODERN_ONLY, Probe())
    async with running_app(server, json_response=True) as (app, _), http_client(app) as client:
        response = await client.post(
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
    body = response.json()
    assert "error" in body, (
        f"a modern-only server must refuse the 2025 handshake, but answered {response.status_code}: {body}"
    )
    assert body["error"]["code"] == UNSUPPORTED_PROTOCOL_VERSION
    assert LATEST_MODERN_VERSION in body["error"]["data"]["supported"]


async def test_legacy_only_server_refuses_an_enveloped_modern_request_over_http_in_legacy_vocabulary() -> None:
    """A server declared LEGACY_ONLY meets an enveloped 2026 request over streamable HTTP:
    it must not serve it under the modern era, and it refuses in legacy vocabulary - an HTTP
    4xx or a legacy-space JSON-RPC error, never a served result and never the modern-only
    -32022 that would tell an auto-negotiating client not to fall back to `initialize`."""
    server = make_postured_server(Posture.LEGACY_ONLY, Probe())
    async with running_app(server, json_response=True) as (app, _), http_client(app) as client:
        response = await client.post(
            "/mcp",
            headers={**JSON_HEADERS, MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION},
            json={
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {"name": "fast", "arguments": {}, "_meta": dict(MODERN_ENVELOPE)},
            },
        )
    # Every refusal path an HTTP entry has today carries a JSON body; a bodyless 4xx
    # would surface here as a decode error, which still fails the test with its reason.
    payload: dict[str, Any] = response.json()
    assert "result" not in payload, (
        f"a legacy-only server must not serve an enveloped modern request, but did: {payload}"
    )
    error_code: Any = payload.get("error", {}).get("code")
    assert response.status_code >= 400 or error_code is not None, (
        f"the refusal must be an HTTP 4xx or a JSON-RPC error, got {response.status_code}: {payload}"
    )
    assert error_code != UNSUPPORTED_PROTOCOL_VERSION, (
        "a legacy-only server must refuse in legacy vocabulary; -32022 tells an auto-negotiating "
        f"client not to fall back to initialize: {payload}"
    )
