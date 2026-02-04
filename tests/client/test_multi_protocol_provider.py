"""Regression tests for MultiProtocolAuthProvider and credential helpers."""

import httpx
import pytest

from mcp.client.auth.multi_protocol import (
    MultiProtocolAuthProvider,
    OAuthTokenStorageAdapter,
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


class _MockApiKeyProtocol:
    protocol_id = "api_key"
    protocol_version = "1.0"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        return APIKeyCredentials(protocol_id="api_key", api_key=self._api_key)

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        assert isinstance(credentials, APIKeyCredentials)
        request.headers["X-API-Key"] = credentials.api_key

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return isinstance(credentials, APIKeyCredentials) and bool(credentials.api_key)

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


@pytest.mark.anyio
async def test_401_flow_falls_back_when_default_protocol_not_injected() -> None:
    """When server suggests default oauth2 but only api_key instance is injected, fallback to api_key and retry."""
    requests: list[httpx.Request] = []
    api_key = "demo-api-key-12345"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        url = str(request.url)

        if request.method == "GET" and "oauth-protected-resource" in path:
            prm = {
                "resource": "https://rs.example/mcp",
                "authorization_servers": ["https://as.example/"],
                "mcp_auth_protocols": [
                    {"protocol_id": "oauth2", "protocol_version": "2.0", "metadata_url": "https://as.example/.well-known/oauth-authorization-server"},
                    {"protocol_id": "api_key", "protocol_version": "1.0"},
                    {"protocol_id": "mutual_tls", "protocol_version": "1.0"},
                ],
            }
            return httpx.Response(200, json=prm)

        if request.method == "GET" and path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(404, text="not found")

        if request.method == "POST" and path == "/mcp":
            if request.headers.get("x-api-key") == api_key:
                return httpx.Response(
                    200,
                    json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "rs", "version": "1.0"}}},
                )
            # 401 with multi-protocol hints
            www = (
                'Bearer error="invalid_token", '
                'resource_metadata="https://rs.example/.well-known/oauth-protected-resource/mcp", '
                'auth_protocols="oauth2 api_key mutual_tls", '
                'default_protocol="oauth2"'
            )
            return httpx.Response(401, headers={"www-authenticate": www}, text="unauthorized")

        return httpx.Response(500, text=f"unexpected {request.method} {url}")

    transport = httpx.MockTransport(handler)
    storage = _MockStorage()
    proto = _MockApiKeyProtocol(api_key=api_key)

    async with httpx.AsyncClient(transport=transport) as client:
        provider = MultiProtocolAuthProvider(
            server_url="https://rs.example",
            storage=storage,
            protocols=[proto],
            http_client=client,
        )
        client.auth = provider
        r = await client.post("https://rs.example/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1.0"}}})

    assert r.status_code == 200
    # Must have retried POST /mcp with X-API-Key
    post_mcp = [req for req in requests if req.method == "POST" and req.url.path == "/mcp"]
    assert len(post_mcp) >= 2
    assert any(req.headers.get("x-api-key") == api_key for req in post_mcp)


@pytest.mark.anyio
async def test_401_flow_does_not_leak_discovery_response_when_no_protocols_injected() -> None:
    """If no protocol instance is available, final response should correspond to original request (401), not discovery 404."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET" and "oauth-protected-resource" in request.url.path:
            prm = {
                "resource": "https://rs.example/mcp",
                "authorization_servers": ["https://as.example/"],
                "mcp_auth_protocols": [
                    {"protocol_id": "oauth2", "protocol_version": "2.0", "metadata_url": "https://as.example/.well-known/oauth-authorization-server"},
                    {"protocol_id": "api_key", "protocol_version": "1.0"},
                ],
            }
            return httpx.Response(200, json=prm)
        if request.method == "GET" and request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(404, text="not found")
        if request.method == "POST" and request.url.path == "/mcp":
            www = (
                'Bearer error="invalid_token", '
                'resource_metadata="https://rs.example/.well-known/oauth-protected-resource/mcp", '
                'auth_protocols="oauth2 api_key", '
                'default_protocol="oauth2"'
            )
            return httpx.Response(401, headers={"www-authenticate": www}, text="unauthorized")
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    storage = _MockStorage()

    async with httpx.AsyncClient(transport=transport) as client:
        provider = MultiProtocolAuthProvider(
            server_url="https://rs.example",
            storage=storage,
            protocols=[],
            http_client=client,
        )
        client.auth = provider
        r = await client.post("https://rs.example/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1.0"}}})

    assert r.status_code == 401
    # We should have attempted discovery, but final response must not be the discovery 404.
    assert ("GET", "/mcp/.well-known/authorization_servers") in seen


class _OAuthTokenOnlyMockStorage:
    """Minimal storage that only supports OAuthToken (dual contract: oauth2 side)."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens


@pytest.mark.anyio
async def test_oauth_token_storage_adapter_get_tokens_returns_credentials_when_wrapped_has_token() -> None:
    """OAuthTokenStorageAdapter.get_tokens converts OAuthToken to OAuthCredentials."""
    raw = OAuthToken(
        access_token="at",
        token_type="Bearer",
        expires_in=3600,
        scope="read",
        refresh_token="rt",
    )
    wrapped = _OAuthTokenOnlyMockStorage()
    wrapped._tokens = raw
    adapter = OAuthTokenStorageAdapter(wrapped)

    result = await adapter.get_tokens()

    assert result is not None
    assert isinstance(result, OAuthCredentials)
    assert result.protocol_id == "oauth2"
    assert result.access_token == "at"
    assert result.refresh_token == "rt"


@pytest.mark.anyio
async def test_oauth_token_storage_adapter_set_tokens_stores_oauth_token_when_given_credentials() -> None:
    """OAuthTokenStorageAdapter.set_tokens converts OAuthCredentials to OAuthToken and stores."""
    wrapped = _OAuthTokenOnlyMockStorage()
    adapter = OAuthTokenStorageAdapter(wrapped)
    creds = OAuthCredentials(
        protocol_id="oauth2",
        access_token="at",
        token_type="Bearer",
        refresh_token="rt",
        scope="read",
        expires_at=None,
    )

    await adapter.set_tokens(creds)

    assert wrapped._tokens is not None
    assert wrapped._tokens.access_token == "at"
    assert wrapped._tokens.refresh_token == "rt"


@pytest.mark.anyio
async def test_get_credentials_returns_oauth_credentials_when_storage_returns_oauth_token() -> None:
    """MultiProtocolAuthProvider._get_credentials converts OAuthToken from storage to OAuthCredentials (dual contract)."""
    raw = OAuthToken(
        access_token="stored_at",
        token_type="Bearer",
        expires_in=3600,
        scope="read",
    )
    storage = _MockStorage()
    storage._tokens = raw
    provider = MultiProtocolAuthProvider(
        server_url="https://example.com",
        storage=storage,
        protocols=[],
    )
    provider._initialize()

    result = await provider._get_credentials()

    assert result is not None
    assert isinstance(result, OAuthCredentials)
    assert result.access_token == "stored_at"
