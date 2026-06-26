"""End-to-end SEP-990 Identity Assertion (RFC 7523 jwt-bearer) flows.

These exercise the FULL stack: the real `IdentityAssertionOAuthProvider` on the client and the real
authorization-server token endpoint on the server, with `InMemoryAuthorizationServerProvider`
implementing `exchange_identity_assertion`. The client supplies the ID-JAG through its
`assertion_provider` callback; the provider validates it and the issued bearer authorizes the MCP
request.

Recording-first: the recorded `/token` request is asserted before the call result, so a surprise in
the exchange path produces a readable diff of what fired.
"""

from urllib.parse import parse_qsl

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import ListToolsResult, Tool

from mcp.client.auth import OAuthRegistrationError, OAuthTokenError
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider
from mcp.server import Server, ServerRequestContext
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata
from tests.interaction._connect import BASE_URL, mounted_app
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import (
    InMemoryTokenStorage,
    RecordedRequest,
    auth_settings,
    connect_with_oauth,
    record_requests,
)
from tests.interaction.auth._provider import VALID_ASSERTION, InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio

ASM_ROOT = "/.well-known/oauth-authorization-server"
JWT_BEARER_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
ID_JAG_GRANT_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"
CLIENT_ID = "enterprise-mcp-client"
CLIENT_SECRET = "enterprise-secret"
# The AS metadata issuer carries a trailing slash (built from an AnyHttpUrl object); the client
# pins against exactly that.
EXPECTED_ISSUER = f"{BASE_URL}/"


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])


def find(recorded: list[RecordedRequest], method: str, path: str) -> list[RecordedRequest]:
    return [r for r in recorded if r.method == method and r.path == path]


def form_body(request: RecordedRequest) -> dict[str, str]:
    return dict(parse_qsl(request.content.decode()))


def preregister_confidential_client(provider: InMemoryAuthorizationServerProvider) -> None:
    """Seed a pre-registered confidential client allowed to use the identity-assertion grant.

    SEP-990 clients are provisioned out of band (DCR refuses the grant), so the server already knows
    the client; `IdentityAssertionOAuthProvider` presents the same id + secret without registering.
    """
    provider.clients[CLIENT_ID] = OAuthClientInformationFull(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uris=None,
        grant_types=[JWT_BEARER_GRANT_TYPE],
        token_endpoint_auth_method="client_secret_post",
        scope="mcp",
    )


def identity_assertion_provider(
    storage: InMemoryTokenStorage,
    *,
    assertion: str = VALID_ASSERTION,
    expected_issuer: str = EXPECTED_ISSUER,
    record: list[tuple[str, str]] | None = None,
) -> IdentityAssertionOAuthProvider:
    async def assertion_provider(audience: str, resource: str) -> str:
        if record is not None:
            record.append((audience, resource))
        return assertion

    return IdentityAssertionOAuthProvider(
        server_url=f"{BASE_URL}/mcp",
        storage=storage,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        expected_issuer=expected_issuer,
        assertion_provider=assertion_provider,
        scopes="mcp",
    )


@requirement("client-auth:identity-assertion")
async def test_identity_assertion_obtains_a_token_and_authorizes_the_request() -> None:
    """The identity-assertion provider connects end to end with no authorize/register step.

    The full stack runs: the client posts grant_type=jwt-bearer with the ID-JAG as `assertion` to the
    real token endpoint, the provider validates it and issues a bearer, and the bearer authorizes
    list_tools. The recorded sequence proves no /authorize or /register request was made.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    preregister_confidential_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()
    auth = identity_assertion_provider(storage)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=auth_settings(identity_assertion_enabled=True),
            auth=auth,
            on_request=on_request,
        ) as (client, headless):
            result = await client.list_tools()

    # Recording-first: assert what fired before the call result.
    assert headless.authorize_url is None
    assert find(recorded, "GET", "/authorize") == []
    assert find(recorded, "POST", "/register") == []

    [token_req] = find(recorded, "POST", "/token")
    body = form_body(token_req)
    assert body == snapshot(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": "valid-id-jag",
            "client_id": "enterprise-mcp-client",
            "client_secret": "enterprise-secret",
            "resource": "http://127.0.0.1:8000/mcp",
            "scope": "mcp",
        }
    )

    assert result.tools[0].name == "echo"
    assert provider.last_assertion_params is not None
    assert provider.last_assertion_params.assertion == VALID_ASSERTION
    assert storage.tokens is not None
    assert storage.tokens.access_token in provider.access_tokens


@requirement("client-auth:identity-assertion")
async def test_configured_scope_survives_server_scope_selection() -> None:
    """The caller's requested scope reaches the wire even when the AS advertises a broader set.

    The base 401 flow's scope-selection step overwrites `client_metadata.scope` with the
    server-advertised scopes; the provider must send the configured scope regardless. Here the AS
    advertises `mcp extra` but the client requested only `mcp`, so the recorded `/token` body must
    carry `scope=mcp`, not the advertised superset.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    preregister_confidential_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    auth = identity_assertion_provider(InMemoryTokenStorage())

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            # AS metadata advertises a broader scopes_supported than the client requests.
            settings=auth_settings(identity_assertion_enabled=True, valid_scopes=["mcp", "extra"]),
            auth=auth,
            on_request=on_request,
        ) as (client, _):
            await client.list_tools()

    [token_req] = find(recorded, "POST", "/token")
    assert form_body(token_req)["scope"] == "mcp"
    assert provider.last_assertion_params is not None
    assert provider.last_assertion_params.scopes == ["mcp"]


@requirement("client-auth:identity-assertion:assertion-callback")
async def test_assertion_callback_receives_issuer_audience_and_resource() -> None:
    """The assertion_provider gets the AS issuer as audience and the MCP resource identifier."""
    record: list[tuple[str, str]] = []
    provider = InMemoryAuthorizationServerProvider()
    preregister_confidential_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    auth = identity_assertion_provider(InMemoryTokenStorage(), record=record)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=auth_settings(identity_assertion_enabled=True),
            auth=auth,
        ) as (client, _):
            await client.list_tools()

    assert record == [(EXPECTED_ISSUER, f"{BASE_URL}/mcp")]


@requirement("client-auth:identity-assertion:issuer-pinning")
async def test_unexpected_issuer_aborts_before_sending_credentials() -> None:
    """If the discovered AS issuer differs from expected_issuer, no assertion or secret is sent.

    Pinning `_fixed_client_info.issuer` to the expected AS makes the base SEP-2352 guard discard the
    pre-provisioned credentials when the resource server points at a different AS; the registration-
    less client then has nothing to fall back to, so the flow aborts before any /token request - the
    callback is never invoked and the provider never sees an assertion.
    """
    record: list[tuple[str, str]] = []
    provider = InMemoryAuthorizationServerProvider()
    preregister_confidential_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    # The real AS issuer is BASE_URL/, but the client was provisioned for a different one.
    auth = identity_assertion_provider(
        InMemoryTokenStorage(), expected_issuer="https://corp-as.example/", record=record
    )

    with anyio.fail_after(5):
        with pytest.RaisesGroup(pytest.RaisesExc(OAuthRegistrationError), flatten_subgroups=True):
            await connect_with_oauth(
                server,
                provider=provider,
                settings=auth_settings(identity_assertion_enabled=True),
                auth=auth,
            ).__aenter__()

    assert record == []
    assert provider.last_assertion_params is None


@requirement("client-auth:identity-assertion:disabled-rejected")
async def test_identity_assertion_is_rejected_when_disabled_on_the_server() -> None:
    """With the grant disabled, the token endpoint returns unsupported_grant_type and the flow fails."""
    provider = InMemoryAuthorizationServerProvider()
    preregister_confidential_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    auth = identity_assertion_provider(InMemoryTokenStorage())

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthTokenError, match=r"Token exchange failed \(400\):.*unsupported_grant_type"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(
                server,
                provider=provider,
                settings=auth_settings(identity_assertion_enabled=False),
                auth=auth,
            ).__aenter__()

    assert provider.last_assertion_params is None


@requirement("client-auth:identity-assertion:invalid-assertion")
async def test_a_rejected_assertion_aborts_the_flow() -> None:
    """An ID-JAG the provider rejects surfaces as OAuthTokenError; no bearer is issued."""
    provider = InMemoryAuthorizationServerProvider()
    preregister_confidential_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()
    auth = identity_assertion_provider(storage, assertion="forged-id-jag")

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            pytest.RaisesExc(OAuthTokenError, match=r"Token exchange failed \(400\):.*invalid_grant"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(
                server,
                provider=provider,
                settings=auth_settings(identity_assertion_enabled=True),
                auth=auth,
            ).__aenter__()

    assert provider.last_assertion_params is not None
    assert provider.last_assertion_params.assertion == "forged-id-jag"
    assert storage.tokens is None


@requirement("client-auth:identity-assertion:metadata-advertised")
async def test_metadata_advertises_jwt_bearer_grant_and_id_jag_profile() -> None:
    """When enabled, AS metadata lists the jwt-bearer grant and the id-jag grant profile."""
    server = Server("bare")
    provider = InMemoryAuthorizationServerProvider()

    async with mounted_app(
        server, auth=auth_settings(identity_assertion_enabled=True), auth_server_provider=provider
    ) as (http, _):
        response = await http.get(ASM_ROOT)

    assert response.status_code == 200
    metadata = OAuthMetadata.model_validate_json(response.content)
    assert metadata.grant_types_supported is not None
    assert JWT_BEARER_GRANT_TYPE in metadata.grant_types_supported
    assert metadata.authorization_grant_profiles_supported == [ID_JAG_GRANT_PROFILE]
