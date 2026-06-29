"""Authorization-request, token-request, and PKCE wire-level invariants of the SDK's OAuth client.

Each test runs a real `Client` through `connect_with_oauth` and asserts on the parsed authorize
URL and the recorded `/token` form body — the spec-mandated wire shapes `Client` itself cannot
observe. `record_requests` snapshots each request at send time, so the auth flow's in-place
header mutation on retry never affects what was captured for the first attempt.
"""

import base64
import hashlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlsplit

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import ListToolsResult, Tool
from pydantic import AnyHttpUrl, AnyUrl

from mcp.client.auth import OAuthFlowError
from mcp.server import Server, ServerRequestContext
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata
from tests.interaction._connect import BASE_URL
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    REDIRECT_URI,
    HeadlessOAuth,
    InMemoryTokenStorage,
    RecordedRequest,
    auth_settings,
    connect_with_oauth,
    first_challenge_shim,
    record_requests,
    shimmed_app,
)
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio

PRM_PATH = "/.well-known/oauth-protected-resource/mcp"
ASM_PATH = "/.well-known/oauth-authorization-server"


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])


def authorize_params(authorize_url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(authorize_url).query))


def form_body(request: RecordedRequest) -> dict[str, str]:
    return dict(parse_qsl(request.content.decode()))


def find(recorded: list[RecordedRequest], method: str, path: str) -> list[RecordedRequest]:
    return [r for r in recorded if r.method == method and r.path == path]


@dataclass
class RecordedFlow:
    """One completed OAuth connect: every recorded request, plus the parsed authorize URL params."""

    requests: list[RecordedRequest]
    authorize_url: str

    @property
    def authorize(self) -> dict[str, str]:
        return authorize_params(self.authorize_url)

    @property
    def token_request(self) -> RecordedRequest:
        token_posts = find(self.requests, "POST", "/token")
        assert len(token_posts) == 1
        return token_posts[0]


@pytest.fixture
async def recorded_oauth_flow() -> AsyncIterator[RecordedFlow]:
    """One full OAuth connect with default configuration, yielding its recorded wire traffic.

    `valid_scopes` adds `offline_access` to exercise the SEP-2207 auto-append (and the resulting
    `prompt=consent`); `required_scopes` stays `["mcp"]` so the token still passes the bearer middleware.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    settings = auth_settings(required_scopes=["mcp"], valid_scopes=["mcp", "offline_access"])

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, settings=settings, on_request=on_request) as (
            client,
            headless,
        ):
            await client.list_tools()

    assert headless.authorize_url is not None
    yield RecordedFlow(requests=recorded, authorize_url=headless.authorize_url)


@requirement("client-auth:pkce:s256")
@requirement("client-auth:resource-parameter")
@requirement("client-auth:authorize:offline-access-consent")
async def test_the_authorize_url_carries_s256_pkce_and_the_resource_indicator(
    recorded_oauth_flow: RecordedFlow,
) -> None:
    params = recorded_oauth_flow.authorize

    assert sorted(params) == snapshot(
        [
            "client_id",
            "code_challenge",
            "code_challenge_method",
            "prompt",
            "redirect_uri",
            "resource",
            "response_type",
            "scope",
            "state",
        ]
    )
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    # RFC 7636 §4.2 grammar; an S256 challenge is in practice always 43 characters.
    assert 43 <= len(params["code_challenge"]) <= 128
    # Prefix only: the exact resource value hangs on canonical-URI normalisation (a spec ambiguity).
    assert params["resource"].startswith(BASE_URL)
    assert params["state"] != ""

    assert params["scope"].split(" ") == snapshot(["mcp", "offline_access"])
    assert params["prompt"] == "consent"


@requirement("client-auth:pkce:s256")
async def test_the_code_verifier_on_the_token_request_hashes_to_the_code_challenge(
    recorded_oauth_flow: RecordedFlow,
) -> None:
    challenge = recorded_oauth_flow.authorize["code_challenge"]
    verifier = form_body(recorded_oauth_flow.token_request)["code_verifier"]

    # RFC 7636 §4.1 length and `unreserved` charset.
    assert re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=") == challenge


@requirement("client-auth:state:verify")
async def test_a_mismatched_state_on_the_callback_aborts_the_flow() -> None:
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    headless = HeadlessOAuth(state_override="wrong-state")

    with anyio.fail_after(5):
        # The flow runs inside the transport's task group, so the error arrives wrapped in nested
        # exception groups; the match is a prefix because the full message embeds random tokens.
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthFlowError, match="^State parameter mismatch:"), flatten_subgroups=True
        ):
            # The handshake raises inside `Client.__aenter__`, so an `async with` body would be dead code.
            await connect_with_oauth(server, provider=provider, headless=headless).__aenter__()


@requirement("client-auth:authorization-response:iss-verify")
async def test_a_mismatched_iss_on_the_callback_aborts_the_flow() -> None:
    """The callback `iss` is checked against `oauth_metadata.issuer` (RFC 9207); mismatch aborts before /token."""
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    headless = HeadlessOAuth(iss_override="https://attacker.example.com")

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthFlowError, match="^Authorization response iss mismatch:"), flatten_subgroups=True
        ):
            await connect_with_oauth(server, provider=provider, headless=headless).__aenter__()


@requirement("client-auth:resource-parameter")
async def test_the_authorization_code_token_request_carries_grant_type_code_redirect_and_resource(
    recorded_oauth_flow: RecordedFlow,
) -> None:
    token_req = recorded_oauth_flow.token_request
    body = form_body(token_req)

    # Dynamic registration issues a secret and the client defaults to `client_secret_post`, hence `client_secret`.
    assert sorted(body) == snapshot(
        ["client_id", "client_secret", "code", "code_verifier", "grant_type", "redirect_uri", "resource"]
    )
    assert body["grant_type"] == "authorization_code"
    assert body["code"] != ""
    assert body["redirect_uri"] == recorded_oauth_flow.authorize["redirect_uri"]
    assert body["resource"] == recorded_oauth_flow.authorize["resource"]
    assert token_req.headers["content-type"] == "application/x-www-form-urlencoded"


@requirement("client-auth:bearer-header:every-request")
async def test_every_mcp_request_after_auth_carries_the_bearer_header_and_never_a_query_token(
    recorded_oauth_flow: RecordedFlow,
) -> None:
    mcp_posts = find(recorded_oauth_flow.requests, "POST", "/mcp")
    assert len(mcp_posts) >= 3

    # The first POST is the unauthenticated trigger; meaningful only because requests are snapshotted at send time.
    assert "authorization" not in mcp_posts[0].headers
    for r in mcp_posts[1:]:
        assert r.headers["authorization"].startswith("Bearer ")
        assert r.headers["authorization"] != "Bearer "
        assert "access_token" not in dict(r.url.params)


@requirement("client-auth:token-endpoint-auth-method")
async def test_a_client_with_a_secret_authenticates_the_token_request_with_http_basic() -> None:
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    client_info = OAuthClientInformationFull(
        client_id="cid",
        client_secret="s/cret",
        token_endpoint_auth_method="client_secret_basic",
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        grant_types=["authorization_code", "refresh_token"],
        scope="mcp",
    )
    await provider.register_client(client_info)
    storage = InMemoryTokenStorage(client_info=client_info)

    with anyio.fail_after(5):
        async with connect_with_oauth(server, provider=provider, storage=storage, on_request=on_request) as (client, _):
            await client.list_tools()

    assert find(recorded, "POST", "/register") == []
    [token_req] = find(recorded, "POST", "/token")

    # URL-encoded before base64 per RFC 6749 §2.3.1; the secret's `/` makes the encoding observable.
    decoded = base64.b64decode(token_req.headers["authorization"].removeprefix("Basic ")).decode()
    assert decoded == f"{quote('cid', safe='')}:{quote('s/cret', safe='')}"
    assert "client_secret" not in form_body(token_req)


@requirement("client-auth:token-endpoint-auth-method")
async def test_the_registered_auth_method_is_used_regardless_of_as_metadata_advertised_methods() -> None:
    """The shim advertises only `client_secret_basic`, yet the dynamically registered
    `client_secret_post` wins: the SDK reads the registered `token_endpoint_auth_method`, not
    `token_endpoint_auth_methods_supported`. TypeScript and Go consult the AS metadata instead.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    override = OAuthMetadata(
        issuer=AnyHttpUrl(f"{BASE_URL}/"),
        authorization_endpoint=AnyHttpUrl(f"{BASE_URL}/authorize"),
        token_endpoint=AnyHttpUrl(f"{BASE_URL}/token"),
        registration_endpoint=AnyHttpUrl(f"{BASE_URL}/register"),
        scopes_supported=["mcp"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["client_secret_basic"],
    )
    serve = {ASM_PATH: override.model_dump_json(exclude_none=True).encode()}

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, app_shim=lambda app: shimmed_app(app, serve=serve), on_request=on_request
        ) as (client, _):
            await client.list_tools()

    [register] = find(recorded, "POST", "/register")
    assert json.loads(register.content).get("token_endpoint_auth_method") is None

    [token_req] = find(recorded, "POST", "/token")
    body = form_body(token_req)
    assert "client_secret" in body
    assert body["client_secret"] != ""
    assert "authorization" not in token_req.headers


@requirement("client-auth:scope-selection:priority")
async def test_scope_is_selected_from_the_www_authenticate_challenge_over_prm_metadata() -> None:
    """`first_challenge_shim` supplies the 401 because the SDK's bearer middleware never emits
    `scope=` (divergence `hosting:auth:scope-403`); token verification is off so the post-auth
    retry succeeds regardless of the granted scope.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(default_scopes=["from-header"])
    server = Server("guarded", on_list_tools=list_tools)
    settings = auth_settings(required_scopes=["from-prm"], valid_scopes=["from-header", "from-prm"])
    challenge = f'Bearer scope="from-header", resource_metadata="{BASE_URL}{PRM_PATH}"'

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=settings,
            verify_tokens=False,
            app_shim=first_challenge_shim(challenge),
            on_request=on_request,
        ) as (client, headless):
            await client.list_tools()

    assert headless.authorize_url is not None
    assert authorize_params(headless.authorize_url)["scope"] == "from-header"

    [register] = find(recorded, "POST", "/register")
    assert json.loads(register.content)["scope"] == "from-header"


@requirement("client-auth:pkce:refuse-if-unsupported")
async def test_pkce_is_still_sent_when_as_metadata_omits_code_challenge_methods_supported() -> None:
    """The spec says the client MUST refuse here; the SDK proceeds. See the divergence on the requirement."""
    override = OAuthMetadata(
        issuer=AnyHttpUrl(f"{BASE_URL}/"),
        authorization_endpoint=AnyHttpUrl(f"{BASE_URL}/authorize"),
        token_endpoint=AnyHttpUrl(f"{BASE_URL}/token"),
        registration_endpoint=AnyHttpUrl(f"{BASE_URL}/register"),
        scopes_supported=["mcp"],
        grant_types_supported=["authorization_code", "refresh_token"],
    )
    assert override.code_challenge_methods_supported is None
    serve = {ASM_PATH: override.model_dump_json(exclude_none=True).encode()}

    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server, provider=provider, app_shim=lambda app: shimmed_app(app, serve=serve)
        ) as (client, headless):
            result = await client.list_tools()

    assert headless.authorize_url is not None
    params = authorize_params(headless.authorize_url)
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] != ""
    assert result.tools[0].name == "echo"


@requirement("client-auth:authorize:error-surfaces")
async def test_an_authorize_error_on_the_callback_aborts_the_flow_before_the_token_request() -> None:
    """The callback contract is `() -> (code, state)` with no error form, so the failure surfaces
    as an empty code and `OAuthFlowError("No authorization code received")`; the redirect's
    `error` value is never surfaced to the caller (gap noted in the manifest).
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider(deny_authorize=True)
    server = Server("guarded", on_list_tools=list_tools)
    headless = HeadlessOAuth()

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthFlowError, match="^No authorization code received$"), flatten_subgroups=True
        ):
            await connect_with_oauth(server, provider=provider, headless=headless, on_request=on_request).__aenter__()

    assert headless.error == "access_denied"
    assert find(recorded, "POST", "/token") == []
