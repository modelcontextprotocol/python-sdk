"""Regression tests for CredentialVerifier and OAuthTokenVerifier."""

from typing import Any, cast

import pytest
from starlette.requests import Request

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.verifiers import APIKeyVerifier, MultiProtocolAuthBackend, OAuthTokenVerifier


class _MockTokenVerifier:
    """Mock TokenVerifier for testing."""

    def __init__(self) -> None:
        self._tokens: dict[str, AccessToken] = {}

    def add_token(self, token: str, access_token: AccessToken) -> None:
        self._tokens[token] = access_token

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._tokens.get(token)


def _request_with_auth(value: str | None) -> Request:
    scope: dict[str, Any] = {"type": "http", "headers": []}
    if value is not None:
        scope["headers"] = [(b"authorization", value.encode())]
    return Request(scope)


def _request_with_headers(headers: list[tuple[str, str]]) -> Request:
    scope: dict[str, Any] = {"type": "http", "headers": []}
    if headers:
        from starlette.datastructures import Headers

        h = Headers(dict(headers))
        scope["headers"] = h.raw
    return Request(scope)


@pytest.fixture
def mock_token_verifier() -> _MockTokenVerifier:
    return _MockTokenVerifier()


@pytest.fixture
def oauth_verifier(mock_token_verifier: _MockTokenVerifier) -> OAuthTokenVerifier:
    return OAuthTokenVerifier(cast(Any, mock_token_verifier))


@pytest.fixture
def valid_access_token() -> AccessToken:
    return AccessToken(
        token="valid_token",
        client_id="test_client",
        scopes=["read", "write"],
        expires_at=None,
    )


@pytest.mark.anyio
async def test_oauth_token_verifier_returns_none_when_no_auth_header(
    oauth_verifier: OAuthTokenVerifier,
) -> None:
    request = _request_with_auth(None)
    result = await oauth_verifier.verify(request)
    assert result is None


@pytest.mark.anyio
async def test_oauth_token_verifier_returns_none_when_not_bearer(
    oauth_verifier: OAuthTokenVerifier,
) -> None:
    request = _request_with_auth("Basic dXNlcjpwYXNz")
    result = await oauth_verifier.verify(request)
    assert result is None


@pytest.mark.anyio
async def test_oauth_token_verifier_returns_none_when_bearer_but_invalid(
    oauth_verifier: OAuthTokenVerifier,
) -> None:
    request = _request_with_auth("Bearer unknown_token")
    result = await oauth_verifier.verify(request)
    assert result is None


@pytest.mark.anyio
async def test_oauth_token_verifier_returns_access_token_when_valid(
    oauth_verifier: OAuthTokenVerifier,
    mock_token_verifier: _MockTokenVerifier,
    valid_access_token: AccessToken,
) -> None:
    mock_token_verifier.add_token("valid_token", valid_access_token)
    request = _request_with_auth("Bearer valid_token")
    result = await oauth_verifier.verify(request)
    assert result is not None
    assert result.token == "valid_token"
    assert result.client_id == "test_client"


@pytest.mark.anyio
async def test_oauth_token_verifier_accepts_dpop_verifier(
    oauth_verifier: OAuthTokenVerifier,
    mock_token_verifier: _MockTokenVerifier,
    valid_access_token: AccessToken,
) -> None:
    mock_token_verifier.add_token("t", valid_access_token)
    request = _request_with_auth("Bearer t")
    result = await oauth_verifier.verify(request, dpop_verifier=object())
    assert result is not None


@pytest.mark.anyio
async def test_api_key_verifier_returns_none_when_no_key() -> None:
    verifier = APIKeyVerifier(valid_keys={"key1"})
    request = _request_with_headers([])
    result = await verifier.verify(request)
    assert result is None


@pytest.mark.anyio
async def test_api_key_verifier_accepts_x_api_key_header() -> None:
    verifier = APIKeyVerifier(valid_keys={"secret-key-123"})
    request = _request_with_headers([("X-API-Key", "secret-key-123")])
    result = await verifier.verify(request)
    assert result is not None
    assert result.token == "secret-key-123"
    assert result.client_id == "api_key"


@pytest.mark.anyio
async def test_api_key_verifier_accepts_bearer_when_key_in_valid_keys() -> None:
    verifier = APIKeyVerifier(valid_keys={"mykey"})
    request = _request_with_headers([("Authorization", "Bearer mykey")])
    result = await verifier.verify(request)
    assert result is not None
    assert result.token == "mykey"


@pytest.mark.anyio
async def test_api_key_verifier_rejects_authorization_apikey_scheme() -> None:
    verifier = APIKeyVerifier(valid_keys={"mykey"})
    request = _request_with_headers([("Authorization", "ApiKey mykey")])
    result = await verifier.verify(request)
    assert result is None


@pytest.mark.anyio
async def test_api_key_verifier_returns_none_when_key_invalid() -> None:
    verifier = APIKeyVerifier(valid_keys={"valid"})
    request = _request_with_headers([("X-API-Key", "invalid")])
    result = await verifier.verify(request)
    assert result is None


@pytest.mark.anyio
async def test_multi_protocol_backend_returns_first_success() -> None:
    oauth_verifier = OAuthTokenVerifier(cast(Any, _MockTokenVerifier()))
    api_key_verifier = APIKeyVerifier(valid_keys={"k1"})
    backend = MultiProtocolAuthBackend(verifiers=[oauth_verifier, api_key_verifier])
    request = _request_with_headers([("X-API-Key", "k1")])
    result = await backend.verify(request)
    assert result is not None
    assert result.token == "k1"


@pytest.mark.anyio
async def test_multi_protocol_backend_returns_none_when_all_fail() -> None:
    backend = MultiProtocolAuthBackend(
        verifiers=[
            OAuthTokenVerifier(cast(Any, _MockTokenVerifier())),
            APIKeyVerifier(valid_keys=set()),
        ]
    )
    request = _request_with_headers([])
    result = await backend.verify(request)
    assert result is None
