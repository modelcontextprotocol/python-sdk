"""`docs/advanced/identity-assertion.md`: every claim the page makes, proved against the real SDK."""

import inspect
from urllib.parse import parse_qsl

import httpx
import jwt
import pytest
from inline_snapshot import snapshot
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from docs_src.identity_assertion import tutorial001, tutorial002
from docs_src.oauth_clients import tutorial001 as oauth_clients_tutorial001
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import IdentityAssertionParams, ProviderTokenVerifier, TokenError
from mcp.server.auth.settings import AuthSettings

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

MCP_SERVER_URL = "http://localhost:8001/mcp"


class RecordingASGITransport(httpx.ASGITransport):
    """An `httpx.ASGITransport` that appends every (method, path, body) it carries to a shared log."""

    def __init__(self, app: Starlette, log: list[tuple[str, str, bytes]]) -> None:
        super().__init__(app=app)
        self.log = log

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.log.append((request.method, request.url.path, request.content))
        return await super().handle_async_request(request)


async def test_the_provider_is_an_httpx_auth_but_not_an_oauth_client_provider() -> None:
    """tutorial001: same `auth=` slot as the rest of OAuth clients, but nothing is discovered or registered."""
    assert isinstance(tutorial001.oauth, httpx.Auth)
    assert not isinstance(tutorial001.oauth, OAuthClientProvider)


async def test_main_is_the_main_from_the_oauth_clients_page() -> None:
    """The page says `main()` is unchanged to the character from the OAuth clients page."""
    assert inspect.getsource(tutorial001.main) == inspect.getsource(oauth_clients_tutorial001.main)


async def test_a_client_secret_is_required() -> None:
    """tutorial001: the provider refuses to be constructed as a public client."""
    with pytest.raises(ValueError, match="client_secret is required"):
        IdentityAssertionOAuthProvider(
            server_url=MCP_SERVER_URL,
            storage=tutorial001.InMemoryTokenStorage(),
            client_id="finance-agent",
            client_secret="",
            issuer=tutorial002.ISSUER,
            assertion_provider=tutorial001.fetch_id_jag,
        )


async def test_an_issuer_is_required() -> None:
    """tutorial001: the authorization server is configuration, not discovery."""
    with pytest.raises(ValueError, match="issuer is required"):
        IdentityAssertionOAuthProvider(
            server_url=MCP_SERVER_URL,
            storage=tutorial001.InMemoryTokenStorage(),
            client_id="finance-agent",
            client_secret="finance-agent-secret",
            issuer="",
            assertion_provider=tutorial001.fetch_id_jag,
        )


async def test_the_id_jag_is_a_typed_jwt_carrying_the_claims_the_page_lists() -> None:
    """tutorial001: the stand-in IdP signs a real ID-JAG; its header `typ` and claim set are the extension's."""
    assertion = tutorial001.idp_issue_id_jag("alice@example.com", tutorial002.ISSUER, MCP_SERVER_URL)
    assert jwt.get_unverified_header(assertion)["typ"] == "oauth-id-jag+jwt"
    claims = jwt.decode(assertion, tutorial001.IDP_SIGNING_KEY, algorithms=["HS256"], audience=tutorial002.ISSUER)
    assert list(claims) == snapshot(["iss", "sub", "aud", "client_id", "resource", "scope", "jti", "iat", "exp"])
    assert claims["client_id"] == "finance-agent"
    assert claims["resource"] == MCP_SERVER_URL


async def test_a_forged_assertion_is_rejected() -> None:
    """tutorial002: the signature check fails closed with `invalid_grant`."""
    client = tutorial002.REGISTERED_CLIENTS["finance-agent"]
    with pytest.raises(TokenError) as exc_info:
        await tutorial002.provider.exchange_identity_assertion(
            client, IdentityAssertionParams(assertion="not-an-id-jag")
        )
    assert exc_info.value.error == "invalid_grant"
    assert exc_info.value.error_description == "the assertion did not verify"


async def test_an_assertion_for_another_audience_is_rejected() -> None:
    """tutorial002: an ID-JAG whose `aud` is not this authorization server is `invalid_grant`."""
    client = tutorial002.REGISTERED_CLIENTS["finance-agent"]
    assertion = tutorial001.idp_issue_id_jag("alice@example.com", "https://other.example.com/", MCP_SERVER_URL)
    with pytest.raises(TokenError) as exc_info:
        await tutorial002.provider.exchange_identity_assertion(client, IdentityAssertionParams(assertion=assertion))
    assert exc_info.value.error == "invalid_grant"
    assert exc_info.value.error_description == "the assertion did not verify"


async def test_an_assertion_for_an_unknown_resource_is_rejected() -> None:
    """tutorial002: an ID-JAG naming a resource this server does not serve is `invalid_target`."""
    client = tutorial002.REGISTERED_CLIENTS["finance-agent"]
    assertion = tutorial001.idp_issue_id_jag("alice@example.com", tutorial002.ISSUER, "https://other.example.com/mcp")
    with pytest.raises(TokenError) as exc_info:
        await tutorial002.provider.exchange_identity_assertion(client, IdentityAssertionParams(assertion=assertion))
    assert exc_info.value.error == "invalid_target"
    assert exc_info.value.error_description == "the assertion is for a resource this server does not serve"


async def test_a_replayed_assertion_is_rejected() -> None:
    """tutorial002: `jti` is tracked, so presenting the same ID-JAG twice fails the second time."""
    client = tutorial002.REGISTERED_CLIENTS["finance-agent"]
    assertion = tutorial001.idp_issue_id_jag("alice@example.com", tutorial002.ISSUER, MCP_SERVER_URL)
    params = IdentityAssertionParams(assertion=assertion)
    first = await tutorial002.provider.exchange_identity_assertion(client, params)
    assert first.token_type == "Bearer"
    with pytest.raises(TokenError) as exc_info:
        await tutorial002.provider.exchange_identity_assertion(client, params)
    assert exc_info.value.error == "invalid_grant"
    assert exc_info.value.error_description == "the assertion has already been used"


async def test_the_metadata_advertises_the_grant_type_and_the_id_jag_profile() -> None:
    """tutorial002: the flag turns on both the `jwt-bearer` grant type and the grant-profile advertisement."""
    transport = httpx.ASGITransport(app=tutorial002.auth_app)
    async with httpx.AsyncClient(transport=transport, base_url="https://auth.example.com") as http_client:
        response = await http_client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["issuer"] == "https://auth.example.com/"
    assert "urn:ietf:params:oauth:grant-type:jwt-bearer" in metadata["grant_types_supported"]
    assert metadata["authorization_grant_profiles_supported"] == ["urn:ietf:params:oauth:grant-profile:id-jag"]


async def test_the_whole_grant_is_one_token_request() -> None:
    """The `!!! check`: a 401, the well-known fetch, one `POST /token`, the retry; the subject reaches the tool."""
    mcp = MCPServer(
        "Notes",
        token_verifier=ProviderTokenVerifier(tutorial002.provider),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(tutorial002.ISSUER),
            resource_server_url=AnyHttpUrl(MCP_SERVER_URL),
            required_scopes=["notes:read"],
        ),
    )

    @mcp.tool()
    def whoami() -> str:
        """Report which end user the ID-JAG named."""
        token = get_access_token()
        assert token is not None
        assert token.subject is not None
        return f"{token.subject} ({', '.join(token.scopes)})"

    log: list[tuple[str, str, bytes]] = []
    transport = RecordingASGITransport(mcp.streamable_http_app(), log)
    mounts = {"https://auth.example.com": RecordingASGITransport(tutorial002.auth_app, log)}
    async with mcp.session_manager.run():
        async with (
            httpx.AsyncClient(auth=tutorial001.oauth, transport=transport, mounts=mounts) as http_client,
            Client(streamable_http_client(MCP_SERVER_URL, http_client=http_client)) as client,
        ):
            result = await client.call_tool("whoami", {})
    assert result.structured_content == {"result": "alice@example.com (notes:read)"}

    assert [(method, path) for method, path, _ in log] == snapshot(
        [
            ("POST", "/mcp"),
            ("GET", "/.well-known/oauth-authorization-server"),
            ("POST", "/token"),
            ("POST", "/mcp"),
            ("POST", "/mcp"),
            ("POST", "/mcp"),
        ]
    )
    token_request = dict(parse_qsl(log[2][2].decode()))
    assert sorted(token_request) == snapshot(
        ["assertion", "client_id", "client_secret", "grant_type", "resource", "scope"]
    )
    assert token_request["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert token_request["client_id"] == "finance-agent"
    assert token_request["resource"] == MCP_SERVER_URL
    assert token_request["scope"] == "notes:read"
    assert jwt.get_unverified_header(token_request["assertion"]) == snapshot(
        {"alg": "HS256", "typ": "oauth-id-jag+jwt"}
    )
