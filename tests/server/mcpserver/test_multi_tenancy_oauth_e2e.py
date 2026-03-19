"""End-to-end test for multi-tenant isolation through the OAuth + HTTP stack.

This test exercises the full production path that a real deployment would use:

    1. Client sends HTTP request with ``Authorization: Bearer <token>``
    2. ``AuthContextMiddleware`` validates the token via ``TokenVerifier``,
       extracts ``AccessToken.tenant_id``, and sets the ``tenant_id_var``
       contextvar for the duration of the request.
    3. ``StreamableHTTPSessionManager`` binds new sessions to the current
       tenant and rejects cross-tenant session access.
    4. The low-level ``Server._handle_request`` reads ``tenant_id_var`` and
       populates ``ServerRequestContext.tenant_id``.
    5. ``MCPServer`` handlers (e.g. ``_handle_list_tools``) pass
       ``ctx.tenant_id`` to the appropriate manager, which returns only
       the items registered under that tenant.
    6. The client sees only its own tenant's tools/resources/prompts.

Unlike the in-memory E2E tests in ``test_multi_tenancy_e2e.py`` that set
``tenant_id_var`` manually, this test uses a real Starlette app with auth
middleware and HTTP transport to verify the full integration — proving that
tenant_id flows correctly from the OAuth token all the way through to the
handler response.

Key complexity notes:
    - We use ``StubTokenVerifier`` instead of a full OAuth provider because
      the MCP auth stack allows plugging in a custom ``TokenVerifier``. This
      lets us skip the OAuth authorization code flow while still exercising
      the real ``AuthContextMiddleware`` → ``tenant_id_var`` path.
    - ``httpx.ASGITransport`` does NOT send ASGI lifespan events, so
      Starlette's lifespan (which starts ``StreamableHTTPSessionManager.run()``)
      never fires. We work around this with ``_start_lifespan()``, which
      manually sends the lifespan startup/shutdown events to the ASGI app.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
import pytest
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Stub token verifier — maps bearer tokens to AccessTokens with tenant_id
# ---------------------------------------------------------------------------


class StubTokenVerifier(TokenVerifier):
    """Token verifier that recognises hard-coded bearer tokens.

    In production, ``TokenVerifier.verify_token()`` would call an OAuth
    introspection endpoint or decode a JWT. Here we simply look up the
    token in a pre-built dict, returning the corresponding ``AccessToken``
    (which includes ``tenant_id``). This is the minimal surface needed to
    exercise the real auth middleware without a full OAuth server.
    """

    def __init__(self, token_map: dict[str, AccessToken]) -> None:
        self._tokens = token_map

    async def verify_token(self, token: str) -> AccessToken | None:
        # Returns None for unknown tokens, which the auth middleware
        # treats as an authentication failure (HTTP 401).
        return self._tokens.get(token)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _start_lifespan(app: httpx._transports.asgi._ASGIApp) -> AsyncIterator[None]:
    """Manually trigger ASGI lifespan startup/shutdown on a Starlette app.

    Why this is needed:
        ``httpx.ASGITransport`` sends only HTTP request events — it does NOT
        send ASGI lifespan events. However, the Starlette app returned by
        ``MCPServer.streamable_http_app()`` has a lifespan handler that starts
        ``StreamableHTTPSessionManager.run()``. Without lifespan startup, the
        session manager's internal task group is never initialised, and any
        HTTP request that tries to create a session will fail with:
            RuntimeError: Task group is not initialized. Make sure to use run().

    How it works:
        We call the ASGI app directly with a ``lifespan`` scope and provide
        custom ``receive``/``send`` callables that simulate the ASGI server's
        lifespan protocol:
        1. Send ``lifespan.startup`` → app initialises (starts session manager)
        2. Wait for ``lifespan.startup.complete`` from the app
        3. Yield control to the test
        4. On cleanup, send ``lifespan.shutdown`` → app tears down
        5. Wait for ``lifespan.shutdown.complete``, then cancel the task group
    """
    # Events to coordinate the lifespan protocol handshake
    started = anyio.Event()
    shutdown = anyio.Event()
    startup_complete = anyio.Event()
    shutdown_complete = anyio.Event()

    # ASGI lifespan scope — tells the app this is a lifespan connection
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

    async def receive() -> dict[str, str]:
        """Feed lifespan events to the ASGI app.

        Called twice: once for startup (immediately), once for shutdown
        (blocks until the test is done and ``shutdown`` is set).
        """
        if not started.is_set():
            started.set()
            return {"type": "lifespan.startup"}
        # Block here until the test finishes and triggers shutdown
        await shutdown.wait()
        return {"type": "lifespan.shutdown"}

    async def send(message: MutableMapping[str, Any]) -> None:
        """Receive acknowledgements from the ASGI app."""
        if message["type"] == "lifespan.startup.complete":
            startup_complete.set()
        elif message["type"] == "lifespan.shutdown.complete":
            shutdown_complete.set()

    async with anyio.create_task_group() as tg:
        # Run the ASGI app's lifespan handler in the background
        tg.start_soon(app, scope, receive, send)
        # Wait until the app signals that startup is complete
        await startup_complete.wait()
        try:
            yield
        finally:
            # Signal the app to shut down and wait for confirmation
            shutdown.set()
            await shutdown_complete.wait()
            tg.cancel_scope.cancel()


def _build_tenant_server(verifier: StubTokenVerifier) -> MCPServer:
    """Create an MCPServer with auth enabled and tenant-scoped tools.

    The server is configured with:
    - ``token_verifier``: Our stub that maps bearer tokens to AccessTokens
    - ``auth``: AuthSettings that enable the auth middleware stack
      (issuer_url and resource_server_url are fake since we bypass OAuth)

    Tools registered:
    - "query" under tenant "alpha" — simulates an analytics tool
    - "publish" under tenant "beta" — simulates a publishing tool
    - "whoami" under both tenants — reads ctx.tenant_id to prove
      the tenant context is correctly propagated to handlers
    """
    server = MCPServer(
        "tenant-oauth-test",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl("https://mcp.example.com"),
            required_scopes=["read"],
        ),
    )

    # Tenant "alpha" tools — only visible to requests with tenant_id="alpha"
    def alpha_query(sql: str) -> str:
        return f"alpha: {sql}"

    server.add_tool(alpha_query, name="query", tenant_id="alpha")

    # Tenant "beta" tools — only visible to requests with tenant_id="beta"
    def beta_publish(title: str) -> str:
        return f"beta: {title}"

    server.add_tool(beta_publish, name="publish", tenant_id="beta")

    # "whoami" is registered under BOTH tenants (same function, different
    # tenant scopes). This lets us verify that ctx.tenant_id is correctly
    # set for each tenant's request independently.
    def whoami(ctx: Context) -> str:
        return f"tenant={ctx.tenant_id}"

    server.add_tool(whoami, name="whoami", tenant_id="alpha")
    server.add_tool(whoami, name="whoami", tenant_id="beta")

    return server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def token_map() -> dict[str, AccessToken]:
    """Map bearer token strings to AccessToken objects with tenant_id.

    This simulates what a real OAuth token introspection would return:
    each bearer token resolves to an AccessToken containing the tenant_id
    that identifies which tenant the caller belongs to.
    """
    now = int(time.time())
    return {
        # "token-alpha" authenticates as tenant "alpha" with scope "read"
        "token-alpha": AccessToken(
            token="token-alpha",
            client_id="client-1",
            scopes=["read"],
            expires_at=now + 3600,
            tenant_id="alpha",
        ),
        # "token-beta" authenticates as tenant "beta" with scope "read"
        "token-beta": AccessToken(
            token="token-beta",
            client_id="client-2",
            scopes=["read"],
            expires_at=now + 3600,
            tenant_id="beta",
        ),
    }


@pytest.fixture
def verifier(token_map: dict[str, AccessToken]) -> StubTokenVerifier:
    return StubTokenVerifier(token_map)


@pytest.fixture
def tenant_app(verifier: StubTokenVerifier) -> MCPServer:
    return _build_tenant_server(verifier)


@pytest.fixture
def starlette_app(tenant_app: MCPServer) -> Starlette:
    """Build the Starlette ASGI app with DNS rebinding protection disabled.

    Starlette is the ASGI web framework that MCPServer uses under the hood
    for HTTP transport. ``MCPServer.streamable_http_app()`` returns a
    Starlette ``Application`` wired with:
      - Auth middleware (``AuthenticationMiddleware`` + ``AuthContextMiddleware``)
        that validates bearer tokens and sets ``tenant_id_var``
      - A ``StreamableHTTPASGIApp`` route that handles MCP JSON-RPC over HTTP
      - A lifespan handler that starts/stops ``StreamableHTTPSessionManager``
      - Transport security middleware for DNS rebinding protection

    In tests we use ``httpx.ASGITransport`` to send requests directly to
    this ASGI app in-process (no real network). However, ASGITransport
    sends the Host header as just "localhost" without a port, while the
    default DNS rebinding protection expects "localhost:<port>". We disable
    DNS rebinding protection here since it's not relevant to tenant isolation.
    """
    return tenant_app.streamable_http_app(
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_alpha_sees_only_own_tools(starlette_app: Starlette):
    """A client authenticating as tenant 'alpha' sees only alpha's tools.

    Verifies the full path: Bearer token-alpha → AuthContextMiddleware
    extracts tenant_id="alpha" → ToolManager filters to alpha's tools
    → client receives ["query", "whoami"] (not beta's "publish").
    """
    # Start ASGI lifespan to initialise the StreamableHTTPSessionManager
    async with _start_lifespan(starlette_app):
        # Create an HTTP client that sends requests through ASGITransport
        # directly to the Starlette app (no real network involved).
        # The Authorization header is included on every request.
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=starlette_app),
            headers={"Authorization": "Bearer token-alpha"},
        )
        async with http_client:
            # Use the MCP streamable HTTP client to establish a session
            async with streamable_http_client(
                url="http://localhost/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    # List tools — should only see alpha's tools
                    tools = await session.list_tools()
                    tool_names = sorted(t.name for t in tools.tools)
                    assert tool_names == ["query", "whoami"]


async def test_beta_sees_only_own_tools(starlette_app: Starlette):
    """A client authenticating as tenant 'beta' sees only beta's tools.

    Same structure as the alpha test, but with token-beta. Verifies that
    beta sees ["publish", "whoami"] and NOT alpha's "query" tool.
    """
    async with _start_lifespan(starlette_app):
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=starlette_app),
            headers={"Authorization": "Bearer token-beta"},
        )
        async with http_client:
            async with streamable_http_client(
                url="http://localhost/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    tool_names = sorted(t.name for t in tools.tools)
                    assert tool_names == ["publish", "whoami"]


async def test_alpha_can_call_own_tool(starlette_app: Starlette):
    """Tenant alpha can call its own tool and get the correct result.

    Goes beyond list_tools — actually invokes the "query" tool to verify
    that the tool execution path also respects tenant scoping. The tool
    function returns "alpha: <sql>" to confirm the right tool ran.
    """
    async with _start_lifespan(starlette_app):
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=starlette_app),
            headers={"Authorization": "Bearer token-alpha"},
        )
        async with http_client:
            async with streamable_http_client(
                url="http://localhost/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("query", {"sql": "SELECT 1"})
                    texts = [c.text for c in result.content if isinstance(c, TextContent)]
                    assert any("alpha: SELECT 1" in t for t in texts)


async def test_whoami_returns_correct_tenant(starlette_app: Starlette):
    """The whoami tool reports the authenticated tenant identity.

    This is the strongest proof that tenant_id propagates end-to-end:
    the tool reads ``ctx.tenant_id`` (set by the low-level server from
    ``tenant_id_var``, which was set by ``AuthContextMiddleware`` from
    ``AccessToken.tenant_id``). Each tenant gets a different value.

    We test both tenants in a single test to verify isolation within
    the same Starlette app instance (shared session manager).
    """
    async with _start_lifespan(starlette_app):
        # Test both tenants against the same running app
        for token, expected_tenant in [("token-alpha", "alpha"), ("token-beta", "beta")]:
            http_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=starlette_app),
                headers={"Authorization": f"Bearer {token}"},
            )
            async with http_client:
                async with streamable_http_client(
                    url="http://localhost/mcp",
                    http_client=http_client,
                ) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool("whoami", {})
                        texts = [c.text for c in result.content if isinstance(c, TextContent)]
                        assert any(f"tenant={expected_tenant}" in t for t in texts)


async def test_unauthenticated_request_is_rejected(starlette_app: Starlette):
    """A request without a bearer token is rejected by auth middleware.

    Verifies that the auth middleware (enabled by ``AuthSettings`` and
    ``TokenVerifier``) returns HTTP 401 when no Authorization header is
    present. This is a basic security check — without valid credentials,
    no MCP session can be established.

    Unlike the other tests, this one sends a raw HTTP POST instead of
    using the MCP client, since the client would fail to initialise
    (which is the expected behaviour).
    """
    async with _start_lifespan(starlette_app):
        # No Authorization header — should be rejected
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=starlette_app),
        )
        async with http_client:
            # Send a raw JSON-RPC initialize request without auth
            response = await http_client.post(
                "http://localhost/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1"},
                    },
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            # Auth middleware should reject with 401 Unauthorized
            assert response.status_code == 401
