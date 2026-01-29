"""Regression tests for MultiProtocolAuthProvider and credential helpers."""

import httpx
import pytest

from mcp.client.auth.multi_protocol import (
    MultiProtocolAuthProvider,
    TokenStorage,
    _credentials_to_storage,
    _oauth_token_to_credentials,
)
from mcp.client.auth.protocol import AuthContext
from mcp.shared.auth import (
    APIKeyCredentials,
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthCredentials,
    OAuthToken,
    ProtectedResourceMetadata,
)


class _MockStorage(TokenStorage):
    def __init__(self) -> None:
        self._tokens: AuthCredentials | OAuthToken | None = None

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        self._tokens = tokens


class _MockProtocol:
    protocol_id = "test_proto"
    protocol_version = "1.0"
    _prepare_called = False
    _validate_return = True

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        return AuthCredentials(protocol_id="test_proto")

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        _MockProtocol._prepare_called = True

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return _MockProtocol._validate_return

    async def discover_metadata(
        self,
        metadata_url: str | None = None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


@pytest.fixture
def mock_storage() -> _MockStorage:
    return _MockStorage()


@pytest.fixture
def mock_protocol() -> _MockProtocol:
    _MockProtocol._prepare_called = False
    _MockProtocol._validate_return = True
    return _MockProtocol()


@pytest.fixture
def provider(mock_storage: _MockStorage, mock_protocol: _MockProtocol) -> MultiProtocolAuthProvider:
    return MultiProtocolAuthProvider(
        server_url="https://example.com",
        storage=mock_storage,
        protocols=[mock_protocol],
    )


def test_oauth_token_to_credentials() -> None:
    token = OAuthToken(
        access_token="at",
        token_type="Bearer",
        expires_in=3600,
        scope="read",
        refresh_token="rt",
    )
    creds = _oauth_token_to_credentials(token)
    assert isinstance(creds, OAuthCredentials)
    assert creds.protocol_id == "oauth2"
    assert creds.access_token == "at"
    assert creds.refresh_token == "rt"
    assert creds.scope == "read"


def test_credentials_to_storage_oauth_returns_oauth_token() -> None:
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="at",
        refresh_token="rt",
        scope="read",
    )
    out = _credentials_to_storage(creds)
    assert isinstance(out, OAuthToken)
    assert out.access_token == "at"
    assert out.refresh_token == "rt"
    assert out.scope == "read"


def test_credentials_to_storage_api_key_returns_unchanged() -> None:
    creds = APIKeyCredentials(protocol_id="api_key", api_key="key1")
    out = _credentials_to_storage(creds)
    assert out is creds


def test_provider_initialize_builds_protocol_index(provider: MultiProtocolAuthProvider) -> None:
    provider._initialize()
    assert provider._initialized
    assert provider._get_protocol("test_proto") is not None
    assert provider._get_protocol("other") is None


@pytest.mark.anyio
async def test_get_credentials_returns_none_when_storage_empty(
    provider: MultiProtocolAuthProvider,
) -> None:
    creds = await provider._get_credentials()
    assert creds is None


@pytest.mark.anyio
async def test_get_credentials_returns_auth_credentials_from_storage(
    provider: MultiProtocolAuthProvider,
    mock_storage: _MockStorage,
) -> None:
    raw = AuthCredentials(protocol_id="test_proto")
    mock_storage._tokens = raw
    creds = await provider._get_credentials()
    assert creds is raw


@pytest.mark.anyio
async def test_get_credentials_converts_oauth_token_from_storage(
    provider: MultiProtocolAuthProvider,
    mock_storage: _MockStorage,
) -> None:
    mock_storage._tokens = OAuthToken(
        access_token="at",
        token_type="Bearer",
        expires_in=3600,
    )
    creds = await provider._get_credentials()
    assert isinstance(creds, OAuthCredentials)
    assert creds.access_token == "at"


def test_is_credentials_valid_false_when_none(provider: MultiProtocolAuthProvider) -> None:
    provider._initialize()
    assert provider._is_credentials_valid(None) is False


def test_is_credentials_valid_false_when_protocol_unknown(
    provider: MultiProtocolAuthProvider,
) -> None:
    provider._initialize()
    creds = AuthCredentials(protocol_id="unknown_proto")
    assert provider._is_credentials_valid(creds) is False


def test_is_credentials_valid_delegates_to_protocol(
    provider: MultiProtocolAuthProvider,
    mock_protocol: _MockProtocol,
) -> None:
    provider._initialize()
    creds = AuthCredentials(protocol_id="test_proto")
    assert provider._is_credentials_valid(creds) is True
    _MockProtocol._validate_return = False
    assert provider._is_credentials_valid(creds) is False


def test_prepare_request_calls_protocol(
    provider: MultiProtocolAuthProvider,
    mock_protocol: _MockProtocol,
) -> None:
    provider._initialize()
    request = httpx.Request("GET", "https://example.com/")
    creds = AuthCredentials(protocol_id="test_proto")
    provider._prepare_request(request, creds)
    assert _MockProtocol._prepare_called


def test_prepare_request_no_op_when_protocol_missing(
    provider: MultiProtocolAuthProvider,
) -> None:
    _MockProtocol._prepare_called = False
    provider._initialize()
    request = httpx.Request("GET", "https://example.com/")
    creds = AuthCredentials(protocol_id="other")
    provider._prepare_request(request, creds)
    assert _MockProtocol._prepare_called is False
