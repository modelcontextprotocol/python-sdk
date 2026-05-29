"""Token lifecycle, step-up, and registration-variant flows of the SDK's OAuth client.

Every test connects end to end via `connect_with_oauth`; the assertions are recording-first
(the recorded request sequence is asserted before, or independently of, the call result), so a
surprise in the refresh or step-up paths produces a readable diff of what fired rather than an
opaque failure. The provider knobs that drive each scenario are documented per test.
"""

import base64
from collections import Counter
from urllib.parse import parse_qsl, urlsplit

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl, AnyUrl

from mcp import MCPError, types
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider, PrivateKeyJWTOAuthProvider
from mcp.server import Server, ServerRequestContext
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata
from mcp.types import INTERNAL_ERROR, ListToolsResult, Tool
from tests.interaction._connect import BASE_URL
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    REDIRECT_URI,
    InMemoryTokenStorage,
    RecordedRequest,
    auth_settings,
    connect_with_oauth,
    m2m_token_shim,
    metadata_body,
    record_requests,
    shim,
    step_up_shim,
)
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio

PRM_PATH = "/.well-known/oauth-protected-resource/mcp"
ASM_PATH = "/.well-known/oauth-authorization-server"
CIMD_URL = "https://client.example/.well-known/mcp-client"


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])


def form_body(request: RecordedRequest) -> dict[str, str]:
    """Parse an `application/x-www-form-urlencoded` request body into a flat dict."""
    return dict(parse_qsl(request.content.decode()))


def authorize_params(authorize_url: str) -> dict[str, str]:
    """Parse the authorize URL's query string into a flat dict."""
    return dict(parse_qsl(urlsplit(authorize_url).query))


def find(recorded: list[RecordedRequest], method: str, path: str) -> list[RecordedRequest]:
    return [r for r in recorded if r.method == method and r.path == path]


def path_counts(recorded: list[RecordedRequest]) -> Counter[tuple[str, str]]:
    return Counter((r.method, r.path) for r in recorded)


def cimd_supported_metadata() -> bytes:
    """AS metadata advertising `client_id_metadata_document_supported: true` (the SDK server never sets it)."""
    metadata = OAuthMetadata(
        issuer=AnyHttpUrl(f"{BASE_URL}/"),
        authorization_endpoint=AnyHttpUrl(f"{BASE_URL}/authorize"),
        token_endpoint=AnyHttpUrl(f"{BASE_URL}/token"),
        registration_endpoint=AnyHttpUrl(f"{BASE_URL}/register"),
        scopes_supported=["mcp"],
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        client_id_metadata_document_supported=True,
    )
    return metadata_body(metadata)


def seeded_client(provider: InMemoryAuthorizationServerProvider, **kwargs: object) -> OAuthClientInformationFull:
    """Register a client with the provider and return its info, for pre-registration and CIMD scenarios."""
    base: dict[str, object] = {
        "client_id": "preregistered",
        "token_endpoint_auth_method": "none",
        "redirect_uris": [AnyUrl(REDIRECT_URI)],
        "grant_types": ["authorization_code", "refresh_token"],
        "scope": "mcp",
    }
    base.update(kwargs)
    info = OAuthClientInformationFull.model_validate(base)
    assert info.client_id is not None
    provider.clients[info.client_id] = info
    return info


@requirement("client-auth:refresh:transparent")
async def test_an_expired_access_token_is_transparently_refreshed_before_the_next_request() -> None:
    """An access token the client considers expired is refreshed and the new bearer is used.

    The provider tells the client `expires_in=-3600` for the first token while keeping the
    server-side `expires_at` in the future, so the connect's retry succeeds and the next
    request finds the token expired and refreshes. The recorded requests prove exactly one
    `grant_type=refresh_token` exchange carrying the resource indicator, and the bearer used
    after the refresh is the second access token, which is the one persisted to storage.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(issue_expired_first=True)
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"

    token_posts = find(recorded, "POST", "/token")
    bodies = [form_body(r) for r in token_posts]
    assert [b["grant_type"] for b in bodies] == snapshot(["authorization_code", "refresh_token"])

    refresh_body = bodies[1]
    assert sorted(refresh_body) == snapshot(["client_id", "client_secret", "grant_type", "refresh_token", "resource"])
    assert refresh_body["refresh_token"].startswith("refresh_")
    assert refresh_body["resource"].startswith(BASE_URL)

    bearers = {r.headers["authorization"] for r in recorded if r.path == "/mcp" and "authorization" in r.headers}
    assert len(bearers) == 2
    assert storage.tokens is not None
    assert f"Bearer {storage.tokens.access_token}" in bearers
    assert storage.tokens.expires_in == 3600


@requirement("client-auth:403-scope-upgrade")
async def test_a_403_insufficient_scope_triggers_one_reauthorize_with_the_challenged_scope() -> None:
    """A 403 `insufficient_scope` challenge is answered by one re-authorize with the challenge's scope.

    The shim 403s the second authenticated `/mcp` POST (the `notifications/initialized` request,
    which reaches the auth flow's step-up handler; the first authenticated POST is the post-401
    retry, after which the generator ends without inspecting the response). The challenge names a
    wider scope; step-up reuses cached metadata and the existing client registration,
    re-authorizes with the new scope, and the connect completes. The client is pre-registered
    with both scopes so the server's authorize handler accepts the wider second request. One
    re-authorize, one retry; the spec's SHOULD-retry-limit ("a few") is not enforced.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage(client_info=seeded_client(provider, scope="mcp write"))
    server = Server("guarded", on_list_tools=list_tools)
    settings = auth_settings(required_scopes=["mcp"], valid_scopes=["mcp", "write"])
    challenge = 'Bearer error="insufficient_scope", scope="mcp write"'

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            settings=settings,
            app_shim=step_up_shim(challenge),
            on_request=on_request,
        ) as (client, headless):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"

    assert len(headless.authorize_urls) == 2
    assert authorize_params(headless.authorize_urls[0])["scope"] == "mcp"
    assert authorize_params(headless.authorize_urls[1])["scope"] == "mcp write"

    counts = path_counts(recorded)
    assert counts[("GET", PRM_PATH)] == 1
    assert counts[("GET", ASM_PATH)] == 1
    assert counts[("POST", "/register")] == 0
    assert counts[("GET", "/authorize")] == 2
    assert counts[("POST", "/token")] == 2


@requirement("client-auth:401-after-auth-throws")
async def test_a_second_401_after_a_completed_oauth_flow_surfaces_without_looping() -> None:
    """A 401 on the post-auth retry surfaces as an error rather than re-entering discovery.

    The provider rejects every token at verification, so the full flow runs once and the retry
    is 401'd. The auth-flow generator ends after that retry, so the 401 propagates and the
    transport converts it to an INTERNAL_ERROR result, raising during connect. Discovery,
    registration, authorize, and token each ran exactly once: no loop.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(reject_all_tokens=True)
    server = Server("guarded", on_list_tools=list_tools)

    def is_internal_error(error: MCPError) -> bool:
        return error.error.code == INTERNAL_ERROR

    with anyio.fail_after(5):
        with pytest.RaisesGroup(pytest.RaisesExc(MCPError, check=is_internal_error), flatten_subgroups=True):
            # Entering the connect raises during the OAuth handshake (inside `Client.__aenter__`),
            # so an `async with` body would be unreachable; entering explicitly avoids dead code.
            await connect_with_oauth(server, provider=provider, on_request=on_request).__aenter__()

    counts = path_counts(recorded)
    assert counts[("GET", PRM_PATH)] == 1
    assert counts[("GET", ASM_PATH)] == 1
    assert counts[("POST", "/register")] == 1
    assert counts[("GET", "/authorize")] == 1
    assert counts[("POST", "/token")] == 1
    assert counts[("POST", "/mcp")] == 2


@requirement("client-auth:cimd")
async def test_cimd_is_selected_when_the_as_advertises_support_and_a_metadata_url_is_supplied() -> None:
    """A client-ID metadata-document URL is used as `client_id` instead of registering.

    AS metadata is shimmed to advertise `client_id_metadata_document_supported: true`; the
    provider is pre-seeded so the server's authorize and token handlers accept the URL as a
    client_id (the SDK server has no CIMD-aware client lookup of its own). The recorded
    requests prove no `/register` call, the authorize URL's `client_id` is the CIMD URL, the
    token request uses `token_endpoint_auth_method=none`, and storage persists the URL as
    `client_id`.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    seeded_client(provider, client_id=CIMD_URL)
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            client_metadata_url=CIMD_URL,
            app_shim=shim(serve={ASM_PATH: cimd_supported_metadata()}),
            on_request=on_request,
        ) as (client, headless):
            await client.list_tools()

    assert find(recorded, "POST", "/register") == []
    assert headless.authorize_url is not None
    assert authorize_params(headless.authorize_url)["client_id"] == CIMD_URL

    [token_req] = find(recorded, "POST", "/token")
    body = form_body(token_req)
    assert body["client_id"] == CIMD_URL
    assert "client_secret" not in body
    assert "authorization" not in token_req.headers

    assert storage.client_info is not None
    assert storage.client_info.client_id == CIMD_URL
    assert storage.client_info.token_endpoint_auth_method == "none"


@requirement("client-auth:invalid-grant-clears-tokens")
async def test_a_failed_refresh_clears_stored_tokens_and_restarts_the_full_flow() -> None:
    """A non-200 refresh response clears the in-memory tokens and the flow re-runs from discovery.

    The first token is reported expired so the next request refreshes; the provider denies the
    refresh once with `invalid_grant`, the auth flow clears its tokens, the unauthenticated
    request 401s, and discovery, authorize, and token run again. The original registration is
    preserved (`client_info` is not cleared). The SDK clears tokens on any non-200 refresh
    response, not specifically `error=invalid_grant`; `source="sdk"` so this is a precision
    note rather than a divergence.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(issue_expired_first=True, fail_next_refresh=True)
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"

    token_posts = find(recorded, "POST", "/token")
    assert [form_body(r)["grant_type"] for r in token_posts] == snapshot(
        ["authorization_code", "refresh_token", "authorization_code"]
    )

    counts = path_counts(recorded)
    assert counts[("POST", "/register")] == 1
    assert counts[("GET", "/authorize")] == 2
    assert counts[("GET", PRM_PATH)] == 2
    assert counts[("GET", ASM_PATH)] == 2

    assert storage.client_info is not None
    assert storage.tokens is not None
    assert storage.tokens.access_token in provider.access_tokens


@requirement("client-auth:client-credentials")
async def test_client_credentials_provider_obtains_a_token_without_an_authorize_step() -> None:
    """The client-credentials provider connects with no authorize step and a `client_credentials` grant.

    The SDK server's `TokenHandler` does not route `client_credentials`, so the harness shim
    handles it (the shim is harness; the SDK-under-test is the client provider). The recorded
    `/token` body proves the grant type, scope, resource indicator, and HTTP-Basic client
    authentication; no `/authorize` or `/register` request was made.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    auth = ClientCredentialsOAuthProvider(
        server_url=f"{BASE_URL}/mcp",
        storage=InMemoryTokenStorage(),
        client_id="m2m-client",
        client_secret="m2m-secret",
        scopes="mcp",
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            auth=auth,
            app_shim=m2m_token_shim(provider, scopes=["mcp"]),
            on_request=on_request,
        ) as (client, headless):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"
    assert headless.authorize_url is None
    assert find(recorded, "GET", "/authorize") == []
    assert find(recorded, "POST", "/register") == []

    [token_req] = find(recorded, "POST", "/token")
    body = form_body(token_req)
    assert body == snapshot(
        {"grant_type": "client_credentials", "resource": "http://127.0.0.1:8000/mcp", "scope": "mcp"}
    )
    decoded = base64.b64decode(token_req.headers["authorization"].removeprefix("Basic ")).decode()
    assert decoded == "m2m-client:m2m-secret"


@requirement("client-auth:private-key-jwt")
async def test_private_key_jwt_provider_authenticates_the_token_request_with_an_assertion() -> None:
    """The private-key-JWT provider sends a `client_assertion` on the token request, with the issuer as audience.

    The assertion provider is a closure that records the audience it was called with and returns
    a fixed opaque value (the JWT contents are not the SDK's concern here); the test asserts the
    `client_assertion`/`client_assertion_type` form fields and that the audience matches the AS
    metadata's issuer.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    audiences: list[str] = []

    async def assertion_provider(audience: str) -> str:
        audiences.append(audience)
        return "header.payload.sig"

    auth = PrivateKeyJWTOAuthProvider(
        server_url=f"{BASE_URL}/mcp",
        storage=InMemoryTokenStorage(),
        client_id="m2m-jwt-client",
        assertion_provider=assertion_provider,
        scopes="mcp",
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            auth=auth,
            app_shim=m2m_token_shim(provider, scopes=["mcp"]),
            on_request=on_request,
        ) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"
    assert audiences == [f"{BASE_URL}/"]

    [token_req] = find(recorded, "POST", "/token")
    body = form_body(token_req)
    assert body == snapshot(
        {
            "grant_type": "client_credentials",
            "client_assertion": "header.payload.sig",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "resource": "http://127.0.0.1:8000/mcp",
            "scope": "mcp",
        }
    )
    assert "client_secret" not in body
    assert "authorization" not in token_req.headers


@pytest.mark.parametrize(
    ("case", "preseed_storage", "advertise_cimd"),
    [("cimd_unsupported_falls_through_to_dcr", False, False), ("preregistered_beats_cimd", True, True)],
    ids=["cimd_unsupported_falls_through_to_dcr", "preregistered_beats_cimd"],
)
@requirement("client-auth:cimd")
async def test_registration_priority_prefers_preregistered_then_cimd_then_dcr(
    case: str, preseed_storage: bool, advertise_cimd: bool
) -> None:
    """The client picks pre-registration over CIMD over DCR, falling through when each is unavailable.

    Two priority edges are exercised: with a CIMD URL configured but no AS support, DCR runs and
    the registered `client_id` is used; with a CIMD URL configured and AS support but a
    pre-registered client in storage, the stored `client_id` is used and neither CIMD nor DCR
    runs. (The positive CIMD case and pre-registration over DCR are covered by their own tests.)
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()

    expected_client_id: str
    if preseed_storage:
        info = seeded_client(provider)
        storage.client_info = info
        assert info.client_id is not None
        expected_client_id = info.client_id
    else:
        expected_client_id = ""

    app_shim = shim(serve={ASM_PATH: cimd_supported_metadata()}) if advertise_cimd else None

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            client_metadata_url=CIMD_URL,
            app_shim=app_shim,
            on_request=on_request,
        ) as (client, headless):
            await client.list_tools()

    assert headless.authorize_url is not None
    chosen_client_id = authorize_params(headless.authorize_url)["client_id"]
    assert chosen_client_id != CIMD_URL

    if case == "cimd_unsupported_falls_through_to_dcr":
        assert len(find(recorded, "POST", "/register")) == 1
        assert chosen_client_id in provider.clients
    else:
        assert find(recorded, "POST", "/register") == []
        assert chosen_client_id == expected_client_id
