"""Authorization-request, token-request, and PKCE wire-level invariants of the SDK's OAuth client.

Every test connects a real `Client` end to end via `connect_with_oauth`; the assertions are on
the parsed authorize URL and the recorded `/token` form body, because those wire shapes are what
the spec mandates and `Client` cannot observe them. The recording uses `record_requests`, which
snapshots each request at send time so the auth flow's in-place header mutation on retry never
affects what was captured for the first attempt.

Tests #1/#2/#4/#5 share one `recorded_oauth_flow` fixture (one connect, several disjoint
assertions on its recording); the others connect fresh because each needs a different harness
configuration.
"""

import base64
import hashlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast
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
    """Parse the authorize URL's query string into a flat dict (one value per key)."""
    return dict(parse_qsl(urlsplit(authorize_url).query))


def form_body(request: RecordedRequest) -> dict[str, str]:
    """Parse an `application/x-www-form-urlencoded` request body into a flat dict."""
    return dict(parse_qsl(request.content.decode()))


def find(recorded: list[RecordedRequest], method: str, path: str) -> list[RecordedRequest]:
    """Filter recorded requests by method and exact path."""
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
    """Run one full OAuth connect with default configuration and yield its recorded wire traffic.

    `valid_scopes` includes `offline_access` so the AS metadata advertises it and the SDK's
    SEP-2207 auto-append (and the resulting `prompt=consent`) is exercised; `required_scopes`
    stays at `["mcp"]` so the issued token still passes the bearer middleware.
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
    """Every spec-mandated parameter appears on the authorize URL with the right value.

    The full key set is snapshotted so a parameter added or dropped fails the test. The
    `code_challenge` length bound is the RFC 7636 §4.2 grammar; an S256 challenge is in
    practice always 43 characters, so the upper bound is never approached.
    """
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
    assert 43 <= len(params["code_challenge"]) <= 128
    # The exact resource value depends on canonical-URI normalisation (a spec ambiguity); pin
    # the stable prefix so the test does not lock in a trailing-slash decision.
    assert params["resource"].startswith(BASE_URL)
    assert params["state"] != ""

    assert params["scope"].split(" ") == snapshot(["mcp", "offline_access"])
    assert params["prompt"] == "consent"


@requirement("client-auth:pkce:s256")
async def test_the_code_verifier_on_the_token_request_hashes_to_the_code_challenge(
    recorded_oauth_flow: RecordedFlow,
) -> None:
    """The PKCE verifier sent on /token is the S256 pre-image of the challenge sent on /authorize.

    The verifier is also checked against RFC 7636 §4.1's length and `unreserved` charset.
    """
    challenge = recorded_oauth_flow.authorize["code_challenge"]
    verifier = form_body(recorded_oauth_flow.token_request)["code_verifier"]

    assert re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=") == challenge


@requirement("client-auth:state:verify")
async def test_a_mismatched_state_on_the_callback_aborts_the_flow() -> None:
    """A callback whose state does not match the value sent on /authorize raises and stops the flow.

    The auth flow runs inside the streamable-HTTP client's task group, so the `OAuthFlowError`
    reaches the test wrapped in nested single-element exception groups; `pytest.RaisesGroup`
    asserts the leaf type and the SDK-authored message prefix (the full message embeds two
    random tokens).
    """
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)
    headless = HeadlessOAuth(state_override="wrong-state")

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthFlowError, match="^State parameter mismatch:"), flatten_subgroups=True
        ):
            # Entering the connect raises during the OAuth handshake (inside `Client.__aenter__`),
            # so an `async with` body would be unreachable; entering explicitly avoids dead code.
            await connect_with_oauth(server, provider=provider, headless=headless).__aenter__()


@requirement("client-auth:authorization-response:iss-verify")
async def test_a_mismatched_iss_on_the_callback_aborts_the_flow() -> None:
    """A callback whose RFC 9207 iss does not match the authorization server issuer aborts the flow.

    `iss_override` makes the headless callback return an issuer the AS never advertised; the SDK
    compares it to `oauth_metadata.issuer` and raises `OAuthFlowError` before the token exchange.
    """
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
    """The /token form body has exactly the auth-code grant fields, with redirect_uri and resource matching /authorize.

    `client_secret` is present because the SDK's dynamic-registration handler issues a secret
    and the client defaults to `client_secret_post`.
    """
    token_req = recorded_oauth_flow.token_request
    body = form_body(token_req)

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
    """Every MCP request after the flow has `Authorization: Bearer ...` and never `?access_token=`.

    The first /mcp POST is the unauthenticated trigger and is asserted to carry no Authorization
    header; that assertion is only meaningful because the recording snapshots requests at send
    time (the SDK mutates the same request object in place for the retry).
    """
    mcp_posts = find(recorded_oauth_flow.requests, "POST", "/mcp")
    assert len(mcp_posts) >= 3

    assert "authorization" not in mcp_posts[0].headers
    for r in mcp_posts[1:]:
        assert r.headers["authorization"].startswith("Bearer ")
        assert r.headers["authorization"] != "Bearer "
        assert "access_token" not in dict(r.url.params)


@requirement("client-auth:token-endpoint-auth-method")
async def test_a_client_with_a_secret_authenticates_the_token_request_with_http_basic() -> None:
    """A `client_secret_basic` client sends URL-encoded credentials in HTTP Basic, not the body.

    Credentials are URL-encoded before base64 per RFC 6749 §2.3.1; the secret contains `/` so
    the encoding is observable.
    """
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

    decoded = base64.b64decode(token_req.headers["authorization"].removeprefix("Basic ")).decode()
    assert decoded == f"{quote('cid', safe='')}:{quote('s/cret', safe='')}"
    assert "client_secret" not in form_body(token_req)


@requirement("client-auth:token-endpoint-auth-method")
async def test_the_registered_auth_method_is_used_regardless_of_as_metadata_advertised_methods() -> None:
    """The token-endpoint auth method comes from the registered client info, not from AS metadata.

    The shim serves AS metadata advertising only `client_secret_basic`; the client dynamically
    registers and the SDK's registration handler issues `client_secret_post`. The client uses
    `client_secret_post` (secret in the body, no Basic header) because the SDK reads the
    registered `token_endpoint_auth_method`, not `token_endpoint_auth_methods_supported`. Other
    SDKs (TypeScript, Go) do consult the AS metadata; this test pins where the python SDK's
    selection point lives.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    server = Server("guarded", on_list_tools=list_tools)

    override = OAuthMetadata(
        issuer=cast(AnyHttpUrl, BASE_URL),
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
    """When the 401 challenge carries `scope=`, that value is requested instead of the PRM scopes.

    The SDK's bearer middleware never emits `scope=` in WWW-Authenticate (see the divergence
    on `hosting:auth:scope-403`), so the test supplies the first 401 itself via
    `first_challenge_shim` and disables token verification so the post-auth retry succeeds
    regardless of the granted scope. PRM advertises `["from-prm"]` (it mirrors
    `required_scopes`); the challenge says `from-header`; the authorize URL must carry
    `from-header`.
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
    """AS metadata without `code_challenge_methods_supported` does not stop the client sending PKCE.

    The spec says the client MUST refuse to proceed in this case; the SDK proceeds and the flow
    completes. See the divergence on the requirement.
    """
    override = OAuthMetadata(
        issuer=cast(AnyHttpUrl, BASE_URL),
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
    """An `error=` redirect from /authorize aborts the flow with no /token request issued.

    The SDK's callback contract is `() -> (code, state)` with no error form, so the failure is
    observed as an empty code reaching the SDK and `OAuthFlowError("No authorization code
    received")` being raised. The actual `error` value from the redirect is not surfaced to the
    caller; that gap is noted in the manifest.
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
