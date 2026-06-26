import urllib.parse

import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth.extensions.token_exchange import (
    ACCESS_TOKEN_TYPE,
    JWT_TOKEN_TYPE,
    TOKEN_EXCHANGE_GRANT_TYPE,
    TokenExchangeOAuthProvider,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken


class MockTokenStorage:
    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:  # pragma: no cover
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:  # pragma: no cover
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:  # pragma: no cover
        self._client_info = client_info


@pytest.fixture
def mock_storage() -> MockTokenStorage:
    return MockTokenStorage()


def oauth_metadata() -> OAuthMetadata:
    return OAuthMetadata(
        issuer=AnyHttpUrl("https://auth.example.com"),
        authorization_endpoint=AnyHttpUrl("https://auth.example.com/authorize"),
        token_endpoint=AnyHttpUrl("https://auth.example.com/token"),
    )


@pytest.mark.anyio
async def test_initialize_sets_client_info(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:  # pragma: no cover
        return "id-jag"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        subject_token_provider=subject_token_provider,
    )

    await provider._initialize()

    assert provider.context.client_info is not None
    assert provider.context.client_info.client_id == "test-client-id"
    assert provider.context.client_info.grant_types == [TOKEN_EXCHANGE_GRANT_TYPE]
    assert provider.context.client_info.token_endpoint_auth_method == "none"


@pytest.mark.anyio
async def test_public_client_includes_client_id_in_body(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:
        return f"id-jag-for-{audience}"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        subject_token_provider=subject_token_provider,
        scopes="read write",
    )
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    request = await provider._perform_authorization()

    assert request.method == "POST"
    assert str(request.url) == "https://auth.example.com/token"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"

    content = urllib.parse.unquote_plus(request.content.decode())
    assert f"grant_type={TOKEN_EXCHANGE_GRANT_TYPE}" in content
    assert "subject_token=id-jag-for-https://auth.example.com/" in content
    assert f"subject_token_type={JWT_TOKEN_TYPE}" in content
    # SEP-990 yields an MCP access token, so requested_token_type defaults to the access-token URN.
    assert f"requested_token_type={ACCESS_TOKEN_TYPE}" in content
    assert "client_id=test-client-id" in content
    assert "scope=read write" in content
    assert "resource=https://mcp.example.com/mcp" in content
    assert "Authorization" not in request.headers


@pytest.mark.anyio
async def test_confidential_client_uses_client_secret_post(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:
        return "id-jag"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        client_secret="test-client-secret",
        subject_token_provider=subject_token_provider,
    )
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    assert provider.context.client_info is not None
    assert provider.context.client_info.token_endpoint_auth_method == "client_secret_post"

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert "client_id=test-client-id" in content
    assert "client_secret=test-client-secret" in content
    assert "Authorization" not in request.headers


@pytest.mark.anyio
async def test_requested_token_type_and_custom_subject_type(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:
        return "opaque-token"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        subject_token_provider=subject_token_provider,
        subject_token_type=ACCESS_TOKEN_TYPE,
        requested_token_type=ACCESS_TOKEN_TYPE,
    )
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert f"subject_token_type={ACCESS_TOKEN_TYPE}" in content
    assert f"requested_token_type={ACCESS_TOKEN_TYPE}" in content


@pytest.mark.anyio
async def test_requested_token_type_omitted_when_none(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:
        return "id-jag"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        subject_token_provider=subject_token_provider,
        requested_token_type=None,
    )
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert "requested_token_type=" not in content


@pytest.mark.anyio
async def test_confidential_client_uses_client_secret_basic(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:
        return "id-jag"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        client_secret="test-client-secret",
        subject_token_provider=subject_token_provider,
        token_endpoint_auth_method="client_secret_basic",
    )
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    assert provider.context.client_info is not None
    assert provider.context.client_info.token_endpoint_auth_method == "client_secret_basic"

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert request.headers["Authorization"].startswith("Basic ")
    assert "client_secret=" not in content


@pytest.mark.anyio
async def test_no_scope_and_no_resource_on_old_protocol(mock_storage: MockTokenStorage) -> None:
    async def subject_token_provider(audience: str) -> str:
        return "id-jag"

    provider = TokenExchangeOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        subject_token_provider=subject_token_provider,
    )
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2024-11-05"  # pre-resource-param

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert "scope=" not in content
    assert "resource=" not in content
