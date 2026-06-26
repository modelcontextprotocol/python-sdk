import base64
import urllib.parse

import pytest

from mcp.client.auth import OAuthFlowError
from mcp.client.auth.extensions.identity_assertion import (
    JWT_BEARER_GRANT_TYPE,
    IdentityAssertionOAuthProvider,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken

ISSUER = "https://auth.example.com"


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


def oauth_metadata(issuer: str = ISSUER) -> OAuthMetadata:
    # Round-trip through JSON so the issuer keeps its path-less form (no trailing slash), matching
    # what the client discovers over the wire; constructing from an AnyHttpUrl object would add one.
    return OAuthMetadata.model_validate(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
        }
    )


def make_provider(
    mock_storage: MockTokenStorage,
    *,
    assertion: str = "id-jag",
    token_endpoint_auth_method: str = "client_secret_post",
    scopes: str | None = "mcp",
    record: list[tuple[str, str]] | None = None,
) -> IdentityAssertionOAuthProvider:
    async def assertion_provider(audience: str, resource: str) -> str:
        if record is not None:
            record.append((audience, resource))
        return assertion

    return IdentityAssertionOAuthProvider(
        server_url="https://mcp.example.com/mcp",
        storage=mock_storage,
        client_id="test-client-id",
        client_secret="test-client-secret",
        expected_issuer=ISSUER,
        assertion_provider=assertion_provider,
        scopes=scopes,
        token_endpoint_auth_method=token_endpoint_auth_method,  # type: ignore[arg-type]
    )


@pytest.mark.anyio
async def test_initialize_sets_pinned_client_info(mock_storage: MockTokenStorage) -> None:
    provider = make_provider(mock_storage)
    await provider._initialize()

    assert provider.context.client_info is not None
    assert provider.context.client_info.client_id == "test-client-id"
    assert provider.context.client_info.grant_types == [JWT_BEARER_GRANT_TYPE]
    # SEP-2352: credentials are pinned to the expected issuer.
    assert provider.context.client_info.issuer == ISSUER


@pytest.mark.anyio
async def test_jwt_bearer_request_with_secret_post(mock_storage: MockTokenStorage) -> None:
    record: list[tuple[str, str]] = []
    provider = make_provider(mock_storage, assertion="the-id-jag", record=record)
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    request = await provider._perform_authorization()

    assert request.method == "POST"
    assert str(request.url) == f"{ISSUER}/token"

    content = urllib.parse.unquote_plus(request.content.decode())
    assert f"grant_type={JWT_BEARER_GRANT_TYPE}" in content
    assert "assertion=the-id-jag" in content
    assert "subject_token" not in content  # jwt-bearer, not token-exchange
    assert "client_id=test-client-id" in content
    assert "client_secret=test-client-secret" in content
    assert "scope=mcp" in content
    assert "resource=https://mcp.example.com/mcp" in content
    assert "Authorization" not in request.headers

    # The callback gets the AS issuer as audience and the MCP resource identifier.
    assert record == [(ISSUER, "https://mcp.example.com/mcp")]


@pytest.mark.anyio
async def test_jwt_bearer_request_with_secret_basic(mock_storage: MockTokenStorage) -> None:
    provider = make_provider(mock_storage, token_endpoint_auth_method="client_secret_basic")
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2025-06-18"

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert "client_secret=" not in content
    decoded = base64.b64decode(request.headers["Authorization"].removeprefix("Basic ")).decode()
    assert decoded == "test-client-id:test-client-secret"


@pytest.mark.anyio
async def test_no_scope_and_no_resource_on_old_protocol(mock_storage: MockTokenStorage) -> None:
    """Without a configured scope and on a pre-resource-param protocol, neither field is sent."""
    provider = make_provider(mock_storage, scopes=None)
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata()
    provider.context.protocol_version = "2024-11-05"  # pre-resource-param

    request = await provider._perform_authorization()

    content = urllib.parse.unquote_plus(request.content.decode())
    assert f"grant_type={JWT_BEARER_GRANT_TYPE}" in content
    assert "scope=" not in content
    assert "resource=" not in content


@pytest.mark.anyio
async def test_unexpected_issuer_refuses_to_send_assertion(mock_storage: MockTokenStorage) -> None:
    """If the discovered AS issuer differs from expected_issuer, the assertion/secret are never sent."""
    record: list[tuple[str, str]] = []
    provider = make_provider(mock_storage, record=record)
    await provider._initialize()
    provider.context.oauth_metadata = oauth_metadata(issuer="https://attacker.example")
    provider.context.protocol_version = "2025-06-18"

    with pytest.raises(OAuthFlowError, match="does not match expected"):
        await provider._perform_authorization()

    assert record == []  # the assertion provider was never invoked
