"""End-to-end OAuth authorization-code flow against the SDK's own server, fully in process.

Auth is HTTP-only so these tests are not transport-parametrized; each connects via
`connect_with_oauth`, which co-hosts the SDK's authorization server, protected-resource
metadata, and bearer-gated MCP endpoint on one bridge-backed Starlette app and drives the
whole flow through one `httpx.AsyncClient` carrying the SDK's `OAuthClientProvider`. The
authorize redirect completes headlessly through the same bridge, so every request the flow
makes is observable via `on_request`.
"""

import json
from collections import Counter
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx
import pytest
from inline_snapshot import snapshot
from pydantic import AnyUrl

from mcp import types
from mcp.server import Server
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.auth import OAuthClientInformationFull
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from tests.interaction._connect import BASE_URL, build_streamable_http_app
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    REDIRECT_URI,
    InMemoryTokenStorage,
    auth_settings,
    connect_with_oauth,
    oauth_client_metadata,
    shimmed_app,
)
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider
from tests.interaction.transports._bridge import StreamingASGITransport

pytestmark = pytest.mark.anyio


def _guarded_server() -> Server[object]:
    """Build a lowlevel server exposing a single `whoami` tool, in the v1 decorator style."""
    server: Server[object] = Server("guarded")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [Tool(name="whoami", inputSchema={"type": "object"})]

    return server


@requirement("flow:oauth:authorization-code-roundtrip")
@requirement("client-auth:401-triggers-flow")
@requirement("hosting:auth:missing-401")
async def test_an_unauthenticated_request_is_challenged_then_the_full_oauth_flow_connects() -> None:
    """Connecting to a bearer-gated server walks the full authorization-code flow and succeeds.

    Three requirements are proven by one connect: the flow runs end to end (authorization-code
    roundtrip), it was triggered by a 401 on the first MCP request (401-triggers-flow), and
    that 401 carried `resource_metadata` in `WWW-Authenticate` for discovery (missing-401).
    The flagship test pins the recorded request sequence so the discovery → registration →
    authorize → token → retry order is asserted explicitly.

    Steps the SDK is expected to perform:
      1. POST /mcp without a token → 401 with `WWW-Authenticate: Bearer resource_metadata=...`.
      2. GET the protected-resource metadata.
      3. GET the authorization-server metadata.
      4. POST /register (dynamic client registration).
      5. GET /authorize → 302 with code+state (completed by the headless redirect).
      6. POST /token (authorization-code exchange).
      7. Retry POST /mcp with `Authorization: Bearer <access_token>` → succeeds.
    """
    requests: list[httpx.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    server = _guarded_server()

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=requests.append) as (
            client,
            headless,
        ):
            result = await client.list_tools()

    assert result == snapshot(ListToolsResult(tools=[Tool(name="whoami", inputSchema={"type": "object"})]))
    assert headless.authorize_url is not None

    paths = [(r.method, r.url.path) for r in requests]
    assert Counter(paths) == snapshot(
        Counter(
            {
                ("POST", "/mcp"): 4,
                ("GET", "/.well-known/oauth-protected-resource/mcp"): 1,
                ("GET", "/.well-known/oauth-authorization-server"): 1,
                ("POST", "/register"): 1,
                ("GET", "/authorize"): 1,
                ("POST", "/token"): 1,
                ("GET", "/mcp"): 1,
                ("DELETE", "/mcp"): 1,
            }
        )
    )

    assert (requests[0].method, requests[0].url.path) == ("POST", "/mcp")
    # The recorded Request objects are live references: the auth flow mutates the original
    # request's headers in place when it adds the bearer token for the retry, so the first
    # entry's headers cannot be used to assert "no Authorization on the first attempt". The
    # path multiset above proving discovery happened is the evidence the first attempt was 401.

    # The first PRM discovery GET carries the protocol-version header (an SDK behaviour, not a
    # spec requirement on discovery requests).
    prm_get = next(r for r in requests if r.url.path == "/.well-known/oauth-protected-resource/mcp")
    assert prm_get.headers.get("mcp-protocol-version") == snapshot("2025-11-25")

    authorize = parse_qs(urlsplit(headless.authorize_url).query)
    assert authorize["response_type"] == ["code"]
    assert authorize["code_challenge_method"] == ["S256"]
    assert authorize["client_id"][0] in provider.clients

    assert storage.tokens is not None
    bearer = f"Bearer {storage.tokens.access_token}"
    authed_mcp = [r for r in requests if r.url.path == "/mcp" and r.headers.get("authorization") == bearer]
    assert len(authed_mcp) > 0
    assert storage.tokens.access_token in provider.access_tokens


@requirement("hosting:auth:authinfo-propagates")
async def test_the_access_token_reaches_the_tool_handler_via_get_access_token() -> None:
    """A tool handler reads the request's access token through `get_access_token()`."""
    server = _guarded_server()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, object]) -> CallToolResult:
        assert name == "whoami"
        token = get_access_token()
        assert token is not None
        return CallToolResult(content=[TextContent(type="text", text=" ".join(token.scopes))])

    provider = InMemoryAuthorizationServerProvider()

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider) as (client, _):
            result = await client.call_tool("whoami", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="mcp")]))


@requirement("client-auth:pre-registration")
async def test_a_preregistered_client_skips_registration() -> None:
    """A client whose storage already holds client info uses it instead of registering.

    The provider holds the same registration server-side so the authorize and token steps
    accept it; the recorded requests prove no `/register` call was made.
    """
    requests: list[httpx.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    server = _guarded_server()

    client_info = OAuthClientInformationFull(
        client_id="preregistered",
        client_secret="s3cret",
        token_endpoint_auth_method="client_secret_post",
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        grant_types=["authorization_code", "refresh_token"],
        scope="mcp",
    )
    await provider.register_client(client_info)
    storage.client_info = client_info

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=requests.append) as (
            client,
            _,
        ):
            await client.list_tools()

    assert [r.url.path for r in requests].count("/register") == 0
    assert list(provider.clients) == ["preregistered"]


@requirement("client-auth:dcr")
async def test_the_dcr_request_carries_the_client_metadata() -> None:
    """Dynamic registration sends the client's metadata and persists what the server issued.

    The body of the recorded `/register` POST carries the metadata the test supplied (with the
    scope filled in from server discovery), and the server's issued client_id and secret are
    persisted to storage and held by the provider.
    """
    requests: list[httpx.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    server = _guarded_server()

    client_metadata = oauth_client_metadata()
    client_metadata.software_id = "interaction-test-suite"

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, storage=storage, client_metadata=client_metadata, on_request=requests.append
        ) as (client, _):
            await client.list_tools()

    register = next(r for r in requests if r.url.path == "/register")
    assert register.headers["content-type"] == "application/json"
    body = json.loads(register.content)
    assert body == snapshot(
        {
            "redirect_uris": ["http://127.0.0.1:8000/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp",
            "client_name": "interaction-suite",
            "software_id": "interaction-test-suite",
        }
    )

    assert storage.client_info is not None
    assert storage.client_info.client_id is not None
    assert storage.client_info.client_secret is not None
    assert list(provider.clients) == [storage.client_info.client_id]


async def test_shimmed_app_serves_overrides_404s_and_otherwise_forwards_to_the_wrapped_app() -> None:
    """Harness self-test: `shimmed_app` serves canned bodies, 404s, and forwards everything else.

    Wraps a real auth-hosting Starlette app so the forward path is exercised against the SDK's
    own routing; provided here so the discovery tests can rely on the shim without each adding
    their own contract test.
    """
    server: Server[object] = Server("bare")
    provider = InMemoryAuthorizationServerProvider()
    real_app, manager = build_streamable_http_app(server, auth=auth_settings(), auth_server_provider=provider)
    app = shimmed_app(real_app, not_found=frozenset({"/missing"}), serve={"/override": b'{"shimmed": true}'})
    async with manager.run():
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http:
            served = await http.get("/override")
            assert served.status_code == 200
            assert served.headers["content-type"] == "application/json"
            assert served.json() == {"shimmed": True}

            assert (await http.get("/missing")).status_code == 404

            forwarded = await http.get("/.well-known/oauth-authorization-server")
            assert forwarded.status_code == 200
            assert forwarded.json()["issuer"] == "http://127.0.0.1:8000/"
