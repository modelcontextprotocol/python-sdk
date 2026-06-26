"""End-to-end RFC 8693 token-exchange flows (SEP-990 enterprise IdP policy controls).

Unlike the machine-to-machine providers - whose grant the SDK server does not route, so a harness
shim mints their tokens - token exchange is handled by the SDK's own `TokenHandler`. These tests
therefore exercise the FULL stack: the real `TokenExchangeOAuthProvider` on the client and the real
authorization-server token endpoint on the server, with `InMemoryAuthorizationServerProvider`
implementing `exchange_token`. The client supplies the ID-JAG through its `subject_token_provider`
callback; the provider validates it and the issued bearer authorizes the MCP request.

Recording-first: the recorded request sequence is asserted before the call result, so a surprise in
the exchange path produces a readable diff of what fired.
"""

import base64
from typing import Literal
from urllib.parse import parse_qsl

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import ListToolsResult, Tool

from mcp.client.auth import OAuthTokenError
from mcp.client.auth.extensions.token_exchange import TokenExchangeOAuthProvider
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
from tests.interaction.auth._provider import VALID_SUBJECT_TOKEN, InMemoryAuthorizationServerProvider

pytestmark = pytest.mark.anyio

ASM_ROOT = "/.well-known/oauth-authorization-server"
TOKEN_EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
CLIENT_ID = "enterprise-mcp-client"


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])


def find(recorded: list[RecordedRequest], method: str, path: str) -> list[RecordedRequest]:
    return [r for r in recorded if r.method == method and r.path == path]


def form_body(request: RecordedRequest) -> dict[str, str]:
    return dict(parse_qsl(request.content.decode()))


def preregister_token_exchange_client(
    provider: InMemoryAuthorizationServerProvider,
    *,
    client_secret: str | None = None,
    token_endpoint_auth_method: Literal["none", "client_secret_post", "client_secret_basic"] = "none",
) -> None:
    """Seed a pre-registered client allowed to use the token-exchange grant.

    Token-exchange clients are provisioned out of band (no DCR), so the server already knows the
    client_id; `TokenExchangeOAuthProvider` presents the same id without registering. Defaults to a
    public client; pass a secret + auth method for a confidential one.
    """
    provider.clients[CLIENT_ID] = OAuthClientInformationFull(
        client_id=CLIENT_ID,
        client_secret=client_secret,
        redirect_uris=None,
        grant_types=[TOKEN_EXCHANGE_GRANT_TYPE],
        token_endpoint_auth_method=token_endpoint_auth_method,
        scope="mcp",
    )


def token_exchange_provider(
    storage: InMemoryTokenStorage, *, subject_token: str = VALID_SUBJECT_TOKEN, scopes: str | None = "mcp"
) -> tuple[TokenExchangeOAuthProvider, list[str]]:
    """Build the SDK client provider and the list its subject_token_provider records audiences into."""
    audiences: list[str] = []

    async def subject_token_provider(audience: str) -> str:
        audiences.append(audience)
        return subject_token

    auth = TokenExchangeOAuthProvider(
        server_url=f"{BASE_URL}/mcp",
        storage=storage,
        client_id=CLIENT_ID,
        subject_token_provider=subject_token_provider,
        scopes=scopes,
    )
    return auth, audiences


@requirement("client-auth:token-exchange")
async def test_token_exchange_obtains_a_token_and_authorizes_the_request() -> None:
    """The token-exchange provider connects end to end with no authorize/register step.

    The full stack runs: the SDK client posts grant_type=token-exchange to the real token endpoint,
    the provider validates the ID-JAG and issues a bearer, and the bearer authorizes list_tools. The
    recorded sequence proves no /authorize or /register request was made and the exchanged token is
    the one stored.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    preregister_token_exchange_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()
    auth, _ = token_exchange_provider(storage)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=auth_settings(token_exchange_enabled=True),
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
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": "valid-id-jag",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "client_id": "enterprise-mcp-client",
            "resource": "http://127.0.0.1:8000/mcp",
            "scope": "mcp",
        }
    )

    assert result.tools[0].name == "echo"
    assert storage.tokens is not None
    assert storage.tokens.access_token in provider.access_tokens


@requirement("client-auth:token-exchange")
async def test_confidential_token_exchange_client_authenticates_with_basic() -> None:
    """A confidential token-exchange client authenticates to the real token endpoint with HTTP Basic.

    Exercises the seam between `TokenExchangeOAuthProvider` and the server's `ClientAuthenticator`:
    the pre-registered client carries a secret and `client_secret_basic`, the recorded /token request
    carries the Basic credentials (not a body secret), and the exchange still succeeds.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    preregister_token_exchange_client(
        provider, client_secret="te-secret", token_endpoint_auth_method="client_secret_basic"
    )
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()

    async def subject_token_provider(audience: str) -> str:
        return VALID_SUBJECT_TOKEN

    auth = TokenExchangeOAuthProvider(
        server_url=f"{BASE_URL}/mcp",
        storage=storage,
        client_id=CLIENT_ID,
        subject_token_provider=subject_token_provider,
        scopes="mcp",
        client_secret="te-secret",
        token_endpoint_auth_method="client_secret_basic",
    )

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=auth_settings(token_exchange_enabled=True),
            auth=auth,
            on_request=on_request,
        ) as (client, _):
            result = await client.list_tools()

    # Recording-first: the client authenticated with Basic, not a body secret.
    [token_req] = find(recorded, "POST", "/token")
    body = form_body(token_req)
    decoded = base64.b64decode(token_req.headers["authorization"].removeprefix("Basic ")).decode()
    assert decoded == f"{CLIENT_ID}:te-secret"
    assert "client_secret" not in body
    assert body["grant_type"] == TOKEN_EXCHANGE_GRANT_TYPE
    assert result.tools[0].name == "echo"
    assert storage.tokens is not None


@requirement("client-auth:token-exchange")
async def test_token_exchange_adopts_server_scopes_when_client_requests_none() -> None:
    """A client built with no scope adopts the AS-advertised scope during discovery and sends it.

    Proves the scope-selection strategy runs on the token-exchange path too: even though the
    provider was constructed with `scopes=None`, the recorded /token body carries the server's
    `mcp` scope and the issued token is granted that scope.
    """
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    preregister_token_exchange_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()
    auth, _ = token_exchange_provider(storage, scopes=None)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=auth_settings(token_exchange_enabled=True),
            auth=auth,
            on_request=on_request,
        ) as (client, _):
            result = await client.list_tools()

    # Recording-first: assert the sent scope before the call result.
    [token_req] = find(recorded, "POST", "/token")
    assert form_body(token_req)["scope"] == "mcp"
    assert provider.last_exchange_params is not None
    assert provider.last_exchange_params.scopes == ["mcp"]
    assert result.tools[0].name == "echo"
    assert storage.tokens is not None
    assert storage.tokens.scope == "mcp"


@requirement("client-auth:token-exchange:subject-token-callback")
async def test_subject_token_callback_is_invoked_with_the_issuer_audience() -> None:
    """The subject_token_provider receives the AS issuer as audience, and its return becomes subject_token."""
    recorded, on_request = record_requests()
    provider = InMemoryAuthorizationServerProvider()
    preregister_token_exchange_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    auth, audiences = token_exchange_provider(InMemoryTokenStorage())

    with anyio.fail_after(5):
        async with connect_with_oauth(
            server,
            provider=provider,
            settings=auth_settings(token_exchange_enabled=True),
            auth=auth,
            on_request=on_request,
        ) as (client, _):
            await client.list_tools()

    # The AS metadata issuer carries the trailing slash (built from an AnyHttpUrl object); the
    # callback audience must match it exactly.
    assert audiences == [f"{BASE_URL}/"]

    [token_req] = find(recorded, "POST", "/token")
    assert form_body(token_req)["subject_token"] == VALID_SUBJECT_TOKEN
    assert provider.last_exchange_params is not None
    assert provider.last_exchange_params.subject_token == VALID_SUBJECT_TOKEN


@requirement("client-auth:token-exchange:disabled-rejected")
async def test_token_exchange_is_rejected_when_disabled_on_the_server() -> None:
    """With token exchange disabled, the token endpoint returns unsupported_grant_type and the flow fails.

    The provider implements exchange_token, but the flag gates the endpoint, so it is never called.
    The client surfaces the 400 as OAuthTokenError inside the streamable-HTTP task group.
    """
    provider = InMemoryAuthorizationServerProvider()
    preregister_token_exchange_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    auth, _ = token_exchange_provider(InMemoryTokenStorage())

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            # The 400 carries unsupported_grant_type specifically, not just any token failure.
            pytest.RaisesExc(OAuthTokenError, match=r"Token exchange failed \(400\):.*unsupported_grant_type"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(
                server,
                provider=provider,
                settings=auth_settings(token_exchange_enabled=False),
                auth=auth,
            ).__aenter__()

    assert provider.last_exchange_params is None


@requirement("client-auth:token-exchange:invalid-subject-token")
async def test_an_unaccepted_subject_token_aborts_the_flow() -> None:
    """A subject token the provider rejects surfaces as OAuthTokenError; no bearer is issued."""
    provider = InMemoryAuthorizationServerProvider()
    preregister_token_exchange_client(provider)
    server = Server("guarded", on_list_tools=list_tools)
    storage = InMemoryTokenStorage()
    auth, _ = token_exchange_provider(storage, subject_token="forged-id-jag")

    with anyio.fail_after(5):
        with pytest.RaisesGroup(
            # The provider rejected the subject token with invalid_grant specifically.
            pytest.RaisesExc(OAuthTokenError, match=r"Token exchange failed \(400\):.*invalid_grant"),
            flatten_subgroups=True,
        ):
            await connect_with_oauth(
                server,
                provider=provider,
                settings=auth_settings(token_exchange_enabled=True),
                auth=auth,
            ).__aenter__()

    assert provider.last_exchange_params is not None
    assert provider.last_exchange_params.subject_token == "forged-id-jag"
    assert storage.tokens is None


@requirement("client-auth:token-exchange:metadata-advertised")
async def test_metadata_advertises_token_exchange_grant_and_public_client_auth() -> None:
    """When enabled, AS metadata lists the token-exchange grant and the `none` token-endpoint auth method."""
    server = Server("bare")
    provider = InMemoryAuthorizationServerProvider()

    async with mounted_app(server, auth=auth_settings(token_exchange_enabled=True), auth_server_provider=provider) as (
        http,
        _,
    ):
        response = await http.get(ASM_ROOT)

    assert response.status_code == 200
    metadata = OAuthMetadata.model_validate_json(response.content)
    assert metadata.grant_types_supported is not None
    assert TOKEN_EXCHANGE_GRANT_TYPE in metadata.grant_types_supported
    assert metadata.token_endpoint_auth_methods_supported is not None
    assert "none" in metadata.token_endpoint_auth_methods_supported
