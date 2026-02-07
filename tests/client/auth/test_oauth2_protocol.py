"""Unit tests for OAuth2Protocol thin adapter.

Covers:
- authenticate delegation to run_authentication
- prepare_request
- validate_credentials
- discover_metadata
"""

import httpx
import pytest

from mcp.client.auth.protocol import AuthContext
from mcp.client.auth.protocols.oauth2 import OAuth2Protocol
from mcp.shared.auth import (
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthClientMetadata,
    OAuthCredentials,
    OAuthToken,
    ProtectedResourceMetadata,
)


@pytest.fixture
def client_metadata() -> OAuthClientMetadata:
    from pydantic import AnyUrl

    return OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:8080/callback")],
        grant_types=["authorization_code"],
        scope="read write",
    )


@pytest.fixture
def oauth2_protocol(client_metadata: OAuthClientMetadata) -> OAuth2Protocol:
    return OAuth2Protocol(
        client_metadata=client_metadata,
        redirect_handler=None,
        callback_handler=None,
        timeout=60.0,
    )


def test_oauth2_protocol_id_and_version(oauth2_protocol: OAuth2Protocol) -> None:
    assert oauth2_protocol.protocol_id == "oauth2"
    assert oauth2_protocol.protocol_version == "2.0"


def test_prepare_request_sets_bearer_header(oauth2_protocol: OAuth2Protocol) -> None:
    request = httpx.Request("GET", "https://example.com/")
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="test-token",
        token_type="Bearer",
    )
    oauth2_protocol.prepare_request(request, creds)
    assert request.headers.get("Authorization") == "Bearer test-token"


def test_prepare_request_no_op_when_no_access_token(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    request = httpx.Request("GET", "https://example.com/")
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="",
        token_type="Bearer",
    )
    oauth2_protocol.prepare_request(request, creds)
    assert "Authorization" not in request.headers


def test_validate_credentials_returns_true_for_valid_oauth_creds(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="at",
        token_type="Bearer",
        expires_at=None,
    )
    assert oauth2_protocol.validate_credentials(creds) is True


def test_validate_credentials_returns_false_when_expired(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="at",
        token_type="Bearer",
        expires_at=1,
    )
    assert oauth2_protocol.validate_credentials(creds) is False


def test_validate_credentials_returns_false_for_non_oauth(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    creds = AuthCredentials(protocol_id="api_key", expires_at=None)
    assert oauth2_protocol.validate_credentials(creds) is False


def test_validate_credentials_returns_false_when_no_token(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="",
        token_type="Bearer",
    )
    assert oauth2_protocol.validate_credentials(creds) is False


@pytest.mark.anyio
async def test_discover_metadata_returns_none_without_http_client(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    """Return None without network when no http_client and no oauth2 entry in PRM."""
    result = await oauth2_protocol.discover_metadata(
        metadata_url="https://example.com/.well-known/oauth-authorization-server",
        prm=None,
    )
    assert result is None


@pytest.mark.anyio
async def test_discover_metadata_from_prm_returns_oauth2_entry(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    """Return oauth2 entry directly from prm.mcp_auth_protocols without requiring http_client."""
    from pydantic import AnyHttpUrl

    oauth2_meta = AuthProtocolMetadata(
        protocol_id="oauth2",
        protocol_version="2.0",
        metadata_url=AnyHttpUrl("https://as.example/"),
        endpoints={"authorization_endpoint": AnyHttpUrl("https://as.example/authorize")},
    )
    prm = ProtectedResourceMetadata(
        resource=AnyHttpUrl("https://rs.example/"),
        authorization_servers=[AnyHttpUrl("https://as.example/")],
        mcp_auth_protocols=[oauth2_meta],
    )
    result = await oauth2_protocol.discover_metadata(
        metadata_url=None,
        prm=prm,
    )
    assert result is not None
    assert result.protocol_id == "oauth2"
    assert result.protocol_version == "2.0"
    assert result.metadata_url is not None
    assert str(result.metadata_url) == "https://as.example/"


@pytest.mark.anyio
async def test_authenticate_creates_own_http_client(
    oauth2_protocol: OAuth2Protocol,
    client_metadata: OAuthClientMetadata,
) -> None:
    """OAuth2Protocol.authenticate creates its own httpx client, so context.http_client can be None.

    This tests that the method doesn't crash when http_client is None.
    It will still fail during OAuth discovery (no server running), but that's expected.
    """
    context = AuthContext(
        server_url="https://example.com",
        storage=None,
        protocol_id="oauth2",
        protocol_metadata=None,
        current_credentials=None,
        dpop_storage=None,
        dpop_enabled=False,
        http_client=None,
        protected_resource_metadata=None,
        scope_from_www_auth=None,
    )
    # Now authenticate creates its own client, so it won't raise ValueError for http_client=None
    # It will fail during OAuth discovery since there's no server, which is expected
    from mcp.client.auth.exceptions import OAuthFlowError

    with pytest.raises(OAuthFlowError, match="Could not discover"):
        await oauth2_protocol.authenticate(context)


@pytest.mark.anyio
async def test_authenticate_delegates_to_run_authentication_and_returns_oauth_credentials(
    oauth2_protocol: OAuth2Protocol,
    client_metadata: OAuthClientMetadata,
) -> None:
    """authenticate(context) delegates to provider.run_authentication.

    Converts current_tokens to OAuthCredentials.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_storage = MagicMock()
    mock_storage.get_tokens = AsyncMock(return_value=None)
    mock_storage.get_client_info = AsyncMock(return_value=None)
    mock_storage.set_tokens = AsyncMock()
    mock_storage.set_client_info = AsyncMock()

    token_after_run = OAuthToken(
        access_token="returned-token",
        token_type="Bearer",
        expires_in=3600,
        scope="read",
        refresh_token="rt",
    )
    mock_provider = MagicMock()
    mock_provider.context = MagicMock()
    mock_provider.context.current_tokens = token_after_run
    mock_provider.run_authentication = AsyncMock()

    async with httpx.AsyncClient() as http_client:
        with patch(
            "mcp.client.auth.protocols.oauth2.OAuthClientProvider",
            return_value=mock_provider,
        ):
            creds = await oauth2_protocol.authenticate(
                AuthContext(
                    server_url="https://example.com",
                    storage=mock_storage,
                    protocol_id="oauth2",
                    protocol_metadata=None,
                    current_credentials=None,
                    dpop_storage=None,
                    dpop_enabled=False,
                    http_client=http_client,
                    protected_resource_metadata=None,
                    scope_from_www_auth=None,
                )
            )
        mock_provider.run_authentication.assert_called_once()
        assert isinstance(creds, OAuthCredentials)
        assert creds.protocol_id == "oauth2"
        assert creds.access_token == "returned-token"
        assert creds.scope == "read"
        assert creds.refresh_token == "rt"


def test_oauth_metadata_to_protocol_metadata_includes_optional_endpoints() -> None:
    from pydantic import AnyHttpUrl

    from mcp.client.auth.protocols.oauth2 import _oauth_metadata_to_protocol_metadata
    from mcp.shared.auth import OAuthMetadata

    asm = OAuthMetadata.model_validate(
        {
            "issuer": "https://as.example",
            "authorization_endpoint": "https://as.example/authorize",
            "token_endpoint": "https://as.example/token",
            "registration_endpoint": "https://as.example/register",
            "revocation_endpoint": "https://as.example/revoke",
            "introspection_endpoint": "https://as.example/introspect",
            "scopes_supported": ["read"],
            "grant_types_supported": ["client_credentials"],
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
        }
    )
    meta = _oauth_metadata_to_protocol_metadata(asm)
    assert meta.protocol_id == "oauth2"
    assert meta.endpoints is not None
    assert meta.endpoints["authorization_endpoint"] == AnyHttpUrl("https://as.example/authorize")
    assert meta.endpoints["token_endpoint"] == AnyHttpUrl("https://as.example/token")
    assert meta.endpoints["registration_endpoint"] == AnyHttpUrl("https://as.example/register")
    assert meta.endpoints["revocation_endpoint"] == AnyHttpUrl("https://as.example/revoke")
    assert meta.endpoints["introspection_endpoint"] == AnyHttpUrl("https://as.example/introspect")


def test_token_to_oauth_credentials_sets_expires_at_when_expires_in_present() -> None:
    from mcp.client.auth.protocols.oauth2 import _token_to_oauth_credentials

    creds = _token_to_oauth_credentials(OAuthToken(access_token="at", token_type="Bearer", expires_in=1))
    assert creds.access_token == "at"
    assert creds.expires_at is not None

    creds2 = _token_to_oauth_credentials(OAuthToken(access_token="at", token_type="Bearer", expires_in=None))
    assert creds2.expires_at is None


@pytest.mark.anyio
async def test_authenticate_reads_protocol_version_and_raises_when_provider_has_no_tokens(
    oauth2_protocol: OAuth2Protocol,
) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from mcp.shared.auth import AuthProtocolMetadata

    mock_storage = MagicMock()
    mock_storage.get_tokens = AsyncMock(return_value=None)
    mock_storage.get_client_info = AsyncMock(return_value=None)
    mock_storage.set_tokens = AsyncMock()
    mock_storage.set_client_info = AsyncMock()

    mock_provider = MagicMock()
    mock_provider.context = MagicMock(current_tokens=None)
    mock_provider.run_authentication = AsyncMock()

    context = AuthContext(
        server_url="https://example.com",
        storage=mock_storage,
        protocol_id="oauth2",
        protocol_metadata=AuthProtocolMetadata(protocol_id="oauth2", protocol_version="2025-06-18"),
        current_credentials=None,
        dpop_storage=None,
        dpop_enabled=False,
        http_client=None,
        protected_resource_metadata=None,
        scope_from_www_auth=None,
    )

    with patch("mcp.client.auth.protocols.oauth2.OAuthClientProvider", return_value=mock_provider):
        with pytest.raises(RuntimeError, match="no tokens"):
            await oauth2_protocol.authenticate(context)


@pytest.mark.anyio
async def test_discover_metadata_network_path_uses_prm_authorization_server_when_metadata_url_missing(
    client_metadata: OAuthClientMetadata,
) -> None:
    protocol = OAuth2Protocol(client_metadata=client_metadata)

    prm = ProtectedResourceMetadata.model_validate(
        {
            "resource": "https://rs.example/mcp",
            "authorization_servers": ["https://as.example/tenant"],
            "mcp_auth_protocols": [{"protocol_id": "api_key", "protocol_version": "1.0"}],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "as.example":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://as.example",
                    "authorization_endpoint": "https://as.example/authorize",
                    "token_endpoint": "https://as.example/token",
                },
                request=request,
            )
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        meta = await protocol.discover_metadata(metadata_url=None, prm=prm, http_client=http_client)

    assert meta is not None
    assert meta.protocol_id == "oauth2"
    assert handler(httpx.Request("GET", "https://rs.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_initialize_dpop_is_idempotent_when_enabled(client_metadata: OAuthClientMetadata) -> None:
    protocol = OAuth2Protocol(client_metadata=client_metadata, dpop_enabled=True)
    assert protocol.get_dpop_public_key_jwk() is None
    await protocol.initialize_dpop()
    await protocol.initialize_dpop()


@pytest.mark.anyio
async def test_discover_metadata_prefers_metadata_url_over_prm_authorization_servers(
    client_metadata: OAuthClientMetadata,
) -> None:
    protocol = OAuth2Protocol(client_metadata=client_metadata)
    prm = ProtectedResourceMetadata.model_validate(
        {
            "resource": "https://rs.example/mcp",
            "authorization_servers": ["https://as.example/tenant"],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "override.example":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://override.example",
                    "authorization_endpoint": "https://override.example/authorize",
                    "token_endpoint": "https://override.example/token",
                },
                request=request,
            )
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        meta = await protocol.discover_metadata(
            metadata_url="https://override.example/.well-known/oauth-authorization-server",
            prm=prm,
            http_client=http_client,
        )

    assert meta is not None
    assert meta.metadata_url is not None
    assert str(meta.metadata_url).startswith("https://override.example/")
    assert handler(httpx.Request("GET", "https://rs.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_discover_metadata_breaks_on_non_4xx_error(client_metadata: OAuthClientMetadata) -> None:
    protocol = OAuth2Protocol(client_metadata=client_metadata)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        meta = await protocol.discover_metadata(
            metadata_url="https://as.example/.well-known/oauth-authorization-server",
            prm=None,
            http_client=http_client,
        )

    assert meta is None
    assert handler(httpx.Request("GET", "https://unexpected.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_discover_metadata_continues_after_validation_error_and_handles_send_exception(
    client_metadata: OAuthClientMetadata,
) -> None:
    protocol = OAuth2Protocol(client_metadata=client_metadata)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/oauth-authorization-server/tenant"):
            return httpx.Response(200, content=b"{bad-json", request=request)
        if url.endswith("/.well-known/openid-configuration/tenant"):
            raise RuntimeError("network down")
        return httpx.Response(
            200,
            json={
                "issuer": "https://as.example",
                "authorization_endpoint": "https://as.example/authorize",
                "token_endpoint": "https://as.example/token",
            },
            request=request,
        )

    prm = ProtectedResourceMetadata.model_validate(
        {"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example/tenant"]}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        meta = await protocol.discover_metadata(metadata_url=None, prm=prm, http_client=http_client)

    assert meta is not None


@pytest.mark.anyio
async def test_discover_metadata_returns_none_when_discovery_urls_are_empty(
    client_metadata: OAuthClientMetadata,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp.client.auth.protocols.oauth2 as oauth2_protocol_module

    def build_urls(auth_server_url: str | None, server_url: str) -> list[str]:
        return []

    monkeypatch.setattr(oauth2_protocol_module, "build_oauth_authorization_server_metadata_discovery_urls", build_urls)
    protocol = OAuth2Protocol(client_metadata=client_metadata)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        meta = await protocol.discover_metadata(
            metadata_url="https://as.example/.well-known/oauth-authorization-server",
            prm=None,
            http_client=http_client,
        )

    assert meta is None
    assert handler(httpx.Request("GET", "https://unexpected.example/unexpected")).status_code == 500
