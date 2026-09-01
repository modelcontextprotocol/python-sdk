"""End-to-end OAuth authorization-code flow against the SDK's own server, fully in process.

Auth is HTTP-only so these tests are not transport-parametrized; each connects via
`connect_with_oauth`, which co-hosts the SDK's authorization server, protected-resource
metadata, and bearer-gated MCP endpoint on one bridge-backed Starlette app and drives the
whole flow through one `httpx2.AsyncClient` carrying the SDK's `OAuthClientProvider`. The
authorize redirect completes headlessly through the same bridge, so every request the flow
makes is observable via `on_request`.
"""

import json
from collections import Counter
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx2
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import PROTOCOL_VERSION_META_KEY, CallToolResult, ListToolsResult, TextContent, Tool
from pydantic import AnyUrl

from mcp.server import Server, ServerRequestContext
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from tests.interaction._connect import BASE_URL
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    REDIRECT_URI,
    InMemoryTokenStorage,
    auth_settings,
    connect_with_oauth,
    oauth_client_metadata,
    record_requests,
    shimmed_app,
)
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider
from tests.interaction.transports._bridge import StreamingASGITransport

pytestmark = pytest.mark.anyio

PRM_PATH = "/.well-known/oauth-protected-resource/mcp"
ASM_PATH = "/.well-known/oauth-authorization-server"


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="whoami", input_schema={"type": "object"})])


async def whoami(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
    """The `whoami` tool answers with the client_id of the access token its request carried."""
    assert params.name == "whoami"
    token = get_access_token()
    assert token is not None
    return CallToolResult(content=[TextContent(text=token.client_id)])


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
    requests: list[httpx2.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=requests.append) as (
            client,
            headless,
        ):
            result = await client.list_tools()

    assert result == snapshot(ListToolsResult(tools=[Tool(name="whoami", input_schema={"type": "object"})]))
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
    assert prm_get.headers.get("mcp-protocol-version") == snapshot("2026-07-28")

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

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "whoami"
        token = get_access_token()
        assert token is not None
        return CallToolResult(content=[TextContent(text=" ".join(token.scopes))])

    server = Server("guarded", on_list_tools=list_tools, on_call_tool=call_tool)
    provider = InMemoryAuthorizationServerProvider()

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider) as (client, _):
            result = await client.call_tool("whoami", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="mcp")]))


@requirement("client-auth:401-triggers-flow")
@requirement("hosting:auth:authinfo-propagates")
async def test_the_authorization_code_flow_completes_on_the_2026_entry_and_the_token_reaches_the_handler() -> None:
    """A client pinned to 2026-07-28 walks the same authorization-code flow and its token reaches the handler.

    There is no handshake on this era, so the pinned client sends nothing on connect and the 401
    that triggers the flow lands on the `tools/call` POST itself (carrying the protocol version
    in `_meta`); discovery, registration, authorize and token follow, and the retried call
    returns the client_id the flow registered.
    """
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    recorded, on_request = record_requests()
    server = Server("guarded", on_list_tools=list_tools, on_call_tool=whoami)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, storage=storage, mode="2026-07-28", on_request=on_request
        ) as (client, _):
            assert client.protocol_version == "2026-07-28"
            result = await client.call_tool("whoami", {})

    assert storage.client_info is not None
    assert result.content == [TextContent(text=storage.client_info.client_id)]

    assert [r.path for r in recorded][:7] == ["/mcp", PRM_PATH, ASM_PATH, "/register", "/authorize", "/token", "/mcp"]
    challenged = json.loads(recorded[0].content)
    assert challenged["method"] == "tools/call"
    assert challenged["params"]["_meta"][PROTOCOL_VERSION_META_KEY] == "2026-07-28"
    assert "authorization" not in recorded[0].headers
    assert storage.tokens is not None
    assert recorded[6].headers["authorization"] == f"Bearer {storage.tokens.access_token}"


@requirement("client-auth:negotiation:auth-before-era")
async def test_an_auto_mode_client_settles_oauth_on_the_discover_probe_then_negotiates_2026() -> None:
    """An auto-negotiating client authorizes first and decides the era second.

    The 401 lands on its unauthenticated `server/discover` probe and drives the flow instead of
    being read as a legacy server's rejection; the probe is then re-sent with the token, answers,
    and the connection settles on 2026-07-28 before the first call.
    """
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    recorded, on_request = record_requests()
    server = Server("guarded", on_list_tools=list_tools, on_call_tool=whoami)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, storage=storage, mode="auto", on_request=on_request
        ) as (client, _):
            assert client.protocol_version == "2026-07-28"
            result = await client.call_tool("whoami", {})

    assert storage.client_info is not None
    assert result.content == [TextContent(text=storage.client_info.client_id)]

    assert [r.path for r in recorded][:7] == ["/mcp", PRM_PATH, ASM_PATH, "/register", "/authorize", "/token", "/mcp"]
    probes = [json.loads(r.content)["method"] for r in recorded[:7] if r.path == "/mcp"]
    assert probes == ["server/discover", "server/discover"]
    assert "authorization" not in recorded[0].headers
    assert storage.tokens is not None
    assert recorded[6].headers["authorization"] == f"Bearer {storage.tokens.access_token}"


@requirement("client-auth:pre-registration")
async def test_a_preregistered_client_skips_registration() -> None:
    """A client whose storage already holds client info uses it instead of registering.

    The provider holds the same registration server-side so the authorize and token steps
    accept it; the recorded requests prove no `/register` call was made.
    """
    requests: list[httpx2.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

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
    requests: list[httpx2.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

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
            "application_type": "native",
            "client_name": "interaction-suite",
            "software_id": "interaction-test-suite",
        }
    )

    assert storage.client_info is not None
    assert storage.client_info.client_id is not None
    assert storage.client_info.client_secret is not None
    assert list(provider.clients) == [storage.client_info.client_id]


@requirement("client-auth:dcr:grant-types-default")
async def test_dcr_defaults_grant_types_to_authorization_code_and_refresh_token_when_omitted() -> None:
    """Registration metadata without `grant_types` sends `["authorization_code", "refresh_token"]`.

    The metadata is built directly rather than via `oauth_client_metadata()`, which sets `grant_types`.
    """
    requests: list[httpx2.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    client_metadata = OAuthClientMetadata(client_name="interaction-suite", redirect_uris=[AnyUrl(REDIRECT_URI)])

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, client_metadata=client_metadata, on_request=requests.append
        ) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "whoami"

    register = next(r for r in requests if r.url.path == "/register")
    assert json.loads(register.content) == snapshot(
        {
            "redirect_uris": ["http://127.0.0.1:8000/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp",
            "application_type": "native",
            "client_name": "interaction-suite",
        }
    )


@requirement("client-auth:dcr:grant-types-default")
async def test_dcr_sends_consumer_set_grant_types_verbatim() -> None:
    """A consumer-set `grant_types` is sent on the registration request verbatim, never rewritten.

    The value deliberately differs from the default pair so pass-through is distinguishable from defaulting.
    """
    requests: list[httpx2.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    client_metadata = OAuthClientMetadata(
        client_name="interaction-suite",
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        grant_types=["authorization_code"],
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, client_metadata=client_metadata, on_request=requests.append
        ) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "whoami"

    register = next(r for r in requests if r.url.path == "/register")
    assert json.loads(register.content)["grant_types"] == ["authorization_code"]


@requirement("client-auth:dcr:app-type-override")
async def test_dcr_sends_a_consumer_set_application_type_verbatim() -> None:
    """A consumer-set `application_type` is sent on the registration request verbatim, never rewritten.

    `"web"` against a loopback redirect URI is deliberately not what redirect-URI derivation
    would produce, so pass-through stays distinguishable from any future derivation strategy.
    The registration echo returns the same value, which the SDK adopts into the persisted
    client info, so a web client reads back web.
    """
    requests: list[httpx2.Request] = []
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()
    client_metadata = OAuthClientMetadata(
        client_name="interaction-suite",
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        application_type="web",
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            client_metadata=client_metadata,
            on_request=requests.append,
        ) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "whoami"

    register = next(r for r in requests if r.url.path == "/register")
    assert json.loads(register.content)["application_type"] == "web"
    assert storage.client_info is not None
    assert storage.client_info.application_type == "web"


async def test_shimmed_app_serves_overrides_404s_and_otherwise_forwards_to_the_wrapped_app() -> None:
    """Harness self-test: `shimmed_app` serves canned bodies, 404s, and forwards everything else.

    Wraps a real auth-hosting Starlette app so the forward path is exercised against the SDK's
    own routing; provided here so the discovery tests can rely on the shim without each adding
    their own contract test.
    """
    server = Server("bare")
    provider = InMemoryAuthorizationServerProvider()
    real_app = server.streamable_http_app(auth=auth_settings(), auth_server_provider=provider)
    app = shimmed_app(real_app, not_found=frozenset({"/missing"}), serve={"/override": b'{"shimmed": true}'})
    async with server.session_manager.run():
        async with httpx2.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http:
            served = await http.get("/override")
            assert served.status_code == 200
            assert served.headers["content-type"] == "application/json"
            assert served.json() == {"shimmed": True}

            assert (await http.get("/missing")).status_code == 404

            forwarded = await http.get("/.well-known/oauth-authorization-server")
            assert forwarded.status_code == 200
            assert forwarded.json()["issuer"] == "http://127.0.0.1:8000/"
