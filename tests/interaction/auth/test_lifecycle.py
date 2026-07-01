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
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import INTERNAL_ERROR, ErrorData, ListToolsResult, Tool
from pydantic import AnyHttpUrl, AnyUrl

from mcp import MCPError
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider, PrivateKeyJWTOAuthProvider
from mcp.server import Server, ServerRequestContext
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken
from tests.interaction._connect import BASE_URL
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    REDIRECT_URI,
    InMemoryTokenStorage,
    RecordedRequest,
    auth_settings,
    connect_with_oauth,
    get_stream_step_up_shim,
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


@requirement("client-auth:refresh:rotation-handling")
async def test_the_rotated_refresh_token_from_a_refresh_response_replaces_the_stored_one() -> None:
    """A new refresh token in a refresh response replaces the stored one (RFC 6749 §6 rotation)."""
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(issue_expired_first=True)
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            await client.list_tools()

    token_posts = find(recorded, "POST", "/token")
    assert [form_body(r)["grant_type"] for r in token_posts] == snapshot(["authorization_code", "refresh_token"])

    presented = form_body(token_posts[1])["refresh_token"]
    assert storage.tokens is not None
    assert storage.tokens.refresh_token != presented
    # The stored token is the one the AS minted; the AS consumed the presented one.
    assert storage.tokens.refresh_token in provider.refresh_tokens
    assert presented not in provider.refresh_tokens


@requirement("client-auth:refresh:rotation-handling")
async def test_a_refresh_response_without_a_refresh_token_preserves_the_stored_one() -> None:
    """A refresh response that omits `refresh_token` leaves the stored one in place.

    RFC 6749 §6 lets the authorization server omit `refresh_token` from a refresh response;
    `rotate_refresh_tokens=False` models that non-rotating AS.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(issue_expired_first=True, rotate_refresh_tokens=False)
    storage = InMemoryTokenStorage()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"

    token_posts = find(recorded, "POST", "/token")
    assert [form_body(r)["grant_type"] for r in token_posts] == snapshot(["authorization_code", "refresh_token"])

    assert storage.tokens is not None
    assert storage.tokens.refresh_token == form_body(token_posts[1])["refresh_token"]
    # expires_in flipping from -3600 proves the refresh response was adopted, not dropped.
    assert storage.tokens.expires_in == 3600

    # The omission triggered no re-authorization or re-registration.
    counts = path_counts(recorded)
    assert counts[("GET", "/authorize")] == 1
    assert counts[("POST", "/register")] == 1


@requirement("client-auth:403-scope-upgrade")
async def test_a_403_insufficient_scope_triggers_one_reauthorize_with_the_challenged_scope() -> None:
    """A 403 `insufficient_scope` challenge is answered by one re-authorize with the challenge's scope.

    The shim 403s the second authenticated `/mcp` POST (the `notifications/initialized` request,
    which reaches the auth flow's step-up handler; the first authenticated POST is the post-401
    retry, after which the generator ends without inspecting the response). The challenge names a
    wider scope; step-up reuses cached metadata and the existing client registration,
    re-authorizes with the new scope, and the connect completes. The client is pre-registered
    with both scopes so the server's authorize handler accepts the wider second request. One
    re-authorize, one retry; the per-send bound is pinned by `client-auth:stepup:retry-cap`.
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


@requirement("client-auth:stepup:scope-union")
async def test_a_403_step_up_re_authorizes_with_the_union_of_prior_and_challenged_scopes() -> None:
    """The step-up re-authorize requests the union of the previously requested and challenged scopes.

    The first authorization requests `mcp`; the 403 challenges a disjoint `write` (not naming
    `mcp`). Per SEP-2350 the client must re-authorize with `mcp write`, not drop `mcp`. The client
    is pre-registered with both scopes so the server's authorize handler accepts the wider request.
    """
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage(client_info=seeded_client(provider, scope="mcp write"))
    server = Server("guarded", on_list_tools=list_tools)
    settings = auth_settings(required_scopes=["mcp"], valid_scopes=["mcp", "write"])
    challenge = 'Bearer error="insufficient_scope", scope="write"'

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            settings=settings,
            app_shim=step_up_shim(challenge),
        ) as (client, headless):
            await client.list_tools()

    assert len(headless.authorize_urls) == 2
    assert authorize_params(headless.authorize_urls[0])["scope"] == "mcp"
    assert authorize_params(headless.authorize_urls[1])["scope"] == "mcp write"


@requirement("client-auth:as-binding:reregister")
@requirement("client-auth:as-binding:no-cred-reuse")
async def test_credentials_bound_to_a_different_issuer_are_discarded_and_the_client_re_registers() -> None:
    """Credentials bound to a stale issuer are dropped and re-registered against the current AS.

    The stored client is bound (SEP-2352) to a different issuer than the one the server's PRM
    advertises, simulating an authorization-server migration. The client must discard it, perform
    Dynamic Client Registration with the current AS, and never present the stale `client_id` at the
    authorize or token endpoints.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    stale = seeded_client(provider, client_id="stale-as-client", issuer="https://old-as.example.com")
    storage = InMemoryTokenStorage(client_info=stale)
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (
            client,
            _,
        ):
            await client.list_tools()

    # The client re-registered with the current AS...
    assert path_counts(recorded)[("POST", "/register")] == 1
    # ...and the stale client_id never reached the authorize or token endpoints.
    authorize_and_token = find(recorded, "GET", "/authorize") + find(recorded, "POST", "/token")
    assert all("stale-as-client" not in r.url.query.decode() for r in authorize_and_token)
    assert all("stale-as-client" not in r.content.decode() for r in find(recorded, "POST", "/token"))
    # The persisted client is now bound to the current AS.
    assert storage.client_info is not None
    assert storage.client_info.client_id != "stale-as-client"
    assert storage.client_info.issuer == f"{BASE_URL}/"


@requirement("client-auth:as-binding:no-token-reuse")
async def test_tokens_from_the_previous_authorization_server_are_never_replayed_after_migration() -> None:
    """Tokens from the previous authorization server are discarded with its credentials, never replayed.

    Storage carries an old-issuer registration plus that server's tokens (SEP-2352); the discard
    must drop both, so the stale refresh token reaches no endpoint of the new authorization server.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    # Not via `seeded_client`: the old AS's client must not be registered with the current provider.
    stale = OAuthClientInformationFull.model_validate(
        {
            "client_id": "stale-as-client",
            "token_endpoint_auth_method": "none",
            "redirect_uris": [AnyUrl(REDIRECT_URI)],
            "grant_types": ["authorization_code", "refresh_token"],
            "scope": "mcp",
            "issuer": "https://old-as.example.com",
        }
    )
    storage = InMemoryTokenStorage(client_info=stale)
    storage.tokens = OAuthToken(
        access_token="stale-access-token",
        token_type="Bearer",
        expires_in=3600,
        scope="mcp",
        refresh_token="stale-refresh-token",
    )
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            result = await client.list_tools()

    token_posts = find(recorded, "POST", "/token")
    assert [form_body(r)["grant_type"] for r in token_posts] == snapshot(["authorization_code"])

    for r in recorded:
        assert "stale-refresh-token" not in r.content.decode()
        assert "stale-refresh-token" not in r.url.query.decode()

    # Non-vacuity: the stale access token was actually presented, and refused.
    stale_bearer_paths = [r.path for r in recorded if r.headers.get("authorization") == "Bearer stale-access-token"]
    assert stale_bearer_paths == ["/mcp"]

    assert path_counts(recorded)[("POST", "/register")] == 1

    assert result.tools[0].name == "echo"
    assert storage.tokens is not None
    assert storage.tokens.refresh_token != "stale-refresh-token"


@requirement("client-auth:as-binding:cimd-portable")
async def test_a_cimd_client_id_survives_an_authorization_server_change_without_reregistration() -> None:
    """A CIMD client_id keeps working across an authorization-server change with no re-registration.

    CIMD client IDs are URLs the authorization server resolves on demand; pre-seeding the
    provider stands in for that resolution (the SDK server has no CIMD-aware client lookup).
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    info = seeded_client(provider, client_id=CIMD_URL, issuer="https://old-as.example.com")
    storage = InMemoryTokenStorage(client_info=info)
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            client_metadata_url=CIMD_URL,
            on_request=on_request,
        ) as (client, headless):
            result = await client.list_tools()

    # The spec sentence itself: "no re-registration is needed when the authorization server changes".
    assert find(recorded, "POST", "/register") == []

    assert headless.authorize_url is not None
    assert authorize_params(headless.authorize_url)["client_id"] == CIMD_URL

    assert result.tools[0].name == "echo"
    assert [form_body(r)["grant_type"] for r in find(recorded, "POST", "/token")] == snapshot(["authorization_code"])

    # The issuer stamp is deliberately not re-stamped on CIMD credentials; a re-stamp fails here consciously.
    assert storage.client_info is not None
    assert storage.client_info.client_id == CIMD_URL
    assert storage.client_info.issuer == "https://old-as.example.com"


@requirement("client-auth:as-binding:prereg-mismatch-error")
async def test_preregistered_credentials_bound_to_a_different_issuer_are_silently_replaced_without_an_error() -> None:
    """Pre-registered credentials with a mismatched issuer are silently replaced rather than erroring.

    The spec's SHOULD-surface-an-error is missed: the SDK cannot tell pre-registered from
    DCR-persisted credentials, so the mismatch takes the discard-and-re-register path -- a recorded divergence.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    prereg = seeded_client(
        provider,
        client_id="prereg-old-as",
        client_secret="prereg-secret",
        token_endpoint_auth_method="client_secret_post",
        issuer="https://old-as.example.com",
    )
    storage = InMemoryTokenStorage(client_info=prereg)
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"

    assert path_counts(recorded)[("POST", "/register")] == 1

    # Only the error half of the SHOULD is missed: the mismatched credential is never presented.
    for r in recorded:
        assert "prereg-old-as" not in r.url.query.decode()
        assert "prereg-old-as" not in r.content.decode()
        assert "prereg-secret" not in r.content.decode()

    assert storage.client_info is not None
    assert storage.client_info.client_id != "prereg-old-as"
    assert storage.client_info.issuer == f"{BASE_URL}/"


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


@requirement("client-auth:stepup:retry-cap")
async def test_a_second_insufficient_scope_403_after_a_step_up_surfaces_without_another_authorize() -> None:
    """A persistent 403 gets one step-up and one retry, then the retried request's 403 surfaces as an error.

    The bound is structural, not a counter: the auth flow re-authorizes once, yields one retry,
    and its generator ends, so the second 403 surfaces as the legacy transport's INTERNAL_ERROR.
    The shim 403s from the third authenticated POST (the `list_tools` request) because the
    client silently drops a non-2xx response to a notification POST.
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
            app_shim=step_up_shim(challenge, on_nth_authenticated_post=3, persist=True),
            on_request=on_request,
        ) as (client, headless):
            # A sync `with` beside an `async with` mis-traces its body arc under branch coverage.
            with pytest.raises(MCPError) as exc_info:  # pragma: no branch
                await client.list_tools()

    assert exc_info.value.error == snapshot(ErrorData(code=INTERNAL_ERROR, message="Server returned an error response"))

    assert len(headless.authorize_urls) == 2
    assert authorize_params(headless.authorize_urls[0])["scope"] == "mcp"
    assert authorize_params(headless.authorize_urls[1])["scope"] == "mcp write"

    # init-retry, initialized, challenged list_tools, retried list_tools -- and no fifth.
    authenticated_posts = [r for r in find(recorded, "POST", "/mcp") if "authorization" in r.headers]
    assert len(authenticated_posts) == 4
    counts = path_counts(recorded)
    assert counts[("POST", "/mcp")] == 5
    assert counts[("POST", "/token")] == 2


@requirement("client-auth:stepup:get-stream-403")
async def test_a_403_on_the_get_stream_open_steps_up_and_reopens_the_stream_with_the_upgraded_token() -> None:
    """A 403 `insufficient_scope` on the standalone GET stream open steps up and reopens the stream.

    The standalone GET (a 2025-11-25 mechanism, removed at 2026-07-28) is opened by the SDK in the
    background and is invisible to `Client`, so the harness shim records each authenticated
    GET's response status and the test waits on the reopened stream's 200 before acting. The
    failure arm stays unpinned: the transport swallows GET failures into a timed reconnect loop
    this suite cannot observe without sleeps.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    storage = InMemoryTokenStorage(client_info=seeded_client(provider, scope="mcp write"))
    server = Server("guarded", on_list_tools=list_tools)
    settings = auth_settings(required_scopes=["mcp"], valid_scopes=["mcp", "write"])
    statuses, reopened, app_shim = get_stream_step_up_shim('Bearer error="insufficient_scope", scope="mcp write"')

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            storage=storage,
            settings=settings,
            app_shim=app_shim,
            on_request=on_request,
        ) as (client, headless):
            await reopened.wait()
            result = await client.list_tools()

    assert result.tools[0].name == "echo"

    assert statuses == [403, 200]

    assert len(headless.authorize_urls) == 2
    assert authorize_params(headless.authorize_urls[0])["scope"] == "mcp"
    assert authorize_params(headless.authorize_urls[1])["scope"] == "mcp write"

    first_get, second_get = find(recorded, "GET", "/mcp")
    assert storage.tokens is not None
    assert second_get.headers["authorization"] == f"Bearer {storage.tokens.access_token}"
    assert first_get.headers["authorization"] != second_get.headers["authorization"]
