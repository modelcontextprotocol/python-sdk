"""单元测试：OAuth2Protocol 薄适配层（authenticate 委托 run_authentication、prepare_request、validate_credentials、discover_metadata）。"""

import httpx
import pytest

from mcp.client.auth.protocol import AuthContext
from mcp.client.auth.protocols.oauth2 import OAuth2Protocol
from mcp.shared.auth import (
    AuthCredentials,
    OAuthClientMetadata,
    OAuthCredentials,
    OAuthToken,
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
    assert oauth2_protocol.protocol_version == "1.0"


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
async def test_discover_metadata_returns_none(oauth2_protocol: OAuth2Protocol) -> None:
    result = await oauth2_protocol.discover_metadata(
        metadata_url="https://example.com/.well-known/oauth-authorization-server",
        prm=None,
    )
    assert result is None


@pytest.mark.anyio
async def test_authenticate_requires_http_client(
    oauth2_protocol: OAuth2Protocol,
    client_metadata: OAuthClientMetadata,
) -> None:
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
    with pytest.raises(ValueError, match="context.http_client"):
        await oauth2_protocol.authenticate(context)


@pytest.mark.anyio
async def test_authenticate_delegates_to_run_authentication_and_returns_oauth_credentials(
    oauth2_protocol: OAuth2Protocol,
    client_metadata: OAuthClientMetadata,
) -> None:
    """authenticate(context) 调用 provider.run_authentication 并从 current_tokens 转为 OAuthCredentials。"""
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
