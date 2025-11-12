import base64
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from mcp.server.auth.handlers.token import (
    AuthorizationCodeRequest,
    ClientCredentialsRequest,
    TokenErrorResponse,
    TokenHandler,
    TokenSuccessResponse,
)
from mcp.server.auth.provider import TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class DummyAuthenticator:
    def __init__(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info

    async def authenticate(self, *, client_id: str, client_secret: str | None) -> OAuthClientInformationFull:
        return self._client_info


class AuthorizationCodeProvider:
    def __init__(self, expected_code: str, code_challenge: str) -> None:
        self.auth_code = SimpleNamespace(
            client_id="client",
            expires_at=time.time() + 60,
            redirect_uri="https://client.example.com/callback",
            redirect_uri_provided_explicitly=False,
            code_challenge=code_challenge,
        )
        self.expected_code = expected_code

    async def load_authorization_code(self, client_info: object, code: str) -> object:
        assert code == self.expected_code
        return self.auth_code

    async def exchange_authorization_code(self, client_info: object, auth_code: object) -> OAuthToken:
        return OAuthToken(access_token="auth-token")


class ClientCredentialsProviderWithError:
    async def exchange_client_credentials(self, client_info: object, scopes: list[str]) -> OAuthToken:
        raise TokenError(error="invalid_client", error_description="bad credentials")


class RefreshTokenProvider:
    def __init__(self) -> None:
        self.refresh_token = SimpleNamespace(
            client_id="client",
            scopes=["alpha"],
            expires_at=None,
        )

    async def load_refresh_token(self, client_info: object, token: str) -> object:
        assert token == "refresh-token"
        return self.refresh_token

    async def exchange_refresh_token(
        self, client_info: object, refresh_token: object, scopes: list[str]
    ) -> OAuthToken:
        return OAuthToken(access_token="refreshed-token")


class DummyRequest:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    async def form(self) -> dict[str, str]:
        return self._data


@pytest.mark.anyio
async def test_handle_authorization_code_with_implicit_redirect() -> None:
    code_verifier = "a" * 64
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    provider = AuthorizationCodeProvider(expected_code="auth-code", code_challenge=code_challenge)
    client_info = OAuthClientInformationFull(client_id="client", grant_types=["authorization_code"])
    handler = TokenHandler(provider=provider, client_authenticator=DummyAuthenticator(client_info))

    request = AuthorizationCodeRequest(
        grant_type="authorization_code",
        code="auth-code",
        redirect_uri=None,
        client_id="client",
        client_secret=None,
        code_verifier=code_verifier,
        resource=None,
    )

    result = await handler._handle_authorization_code(client_info, request)

    assert isinstance(result, TokenSuccessResponse)
    assert result.root.access_token == "auth-token"


@pytest.mark.anyio
async def test_handle_client_credentials_returns_token_error() -> None:
    provider = ClientCredentialsProviderWithError()
    client_info = OAuthClientInformationFull(client_id="client", grant_types=["client_credentials"], scope="")
    handler = TokenHandler(provider=provider, client_authenticator=DummyAuthenticator(client_info))

    request = ClientCredentialsRequest(
        grant_type="client_credentials",
        scope="alpha",
        client_id="client",
        client_secret=None,
    )

    result = await handler._handle_client_credentials(client_info, request)

    assert isinstance(result, TokenErrorResponse)
    assert result.error == "invalid_client"
    assert result.error_description == "bad credentials"


@pytest.mark.anyio
async def test_handle_route_refresh_token_branch() -> None:
    provider = RefreshTokenProvider()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["refresh_token"],
        scope="alpha",
    )
    handler = TokenHandler(provider=provider, client_authenticator=DummyAuthenticator(client_info))

    request_data = {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token",
        "scope": "alpha",
        "client_id": "client",
        "client_secret": "secret",
    }

    response = await handler.handle(DummyRequest(request_data))

    assert response.status_code == 200
    payload = json.loads(response.body.decode())
    assert payload["access_token"] == "refreshed-token"
