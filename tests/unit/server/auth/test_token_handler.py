import base64
import hashlib
import json
import time
from collections.abc import Mapping
from types import MethodType, SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

from mcp.server.auth.handlers.token import (
    AuthorizationCodeRequest,
    ClientCredentialsRequest,
    RefreshTokenRequest,
    TokenErrorResponse,
    TokenHandler,
    TokenRequest,
    TokenSuccessResponse,
)
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class DummyAuthenticator:
    def __init__(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info

    async def authenticate(self, client_id: str, client_secret: str | None) -> OAuthClientInformationFull:
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


class ClientCredentialsProviderSuccess:
    def __init__(self) -> None:
        self.last_scopes: list[str] | None = None

    async def exchange_client_credentials(self, client_info: object, scopes: list[str]) -> OAuthToken:
        self.last_scopes = scopes
        return OAuthToken(access_token="client-token")


class TokenExchangeProviderStub:
    def __init__(self) -> None:
        self.last_call: dict[str, Any] | None = None

    async def exchange_token(
        self,
        client_info: object,
        subject_token: str,
        subject_token_type: str,
        actor_token: str | None,
        actor_token_type: str | None,
        scopes: list[str],
        audience: str | None,
        resource: str | None,
    ) -> OAuthToken:
        self.last_call = {
            "subject_token": subject_token,
            "subject_token_type": subject_token_type,
            "actor_token": actor_token,
            "actor_token_type": actor_token_type,
            "scopes": scopes,
            "audience": audience,
            "resource": resource,
        }
        return OAuthToken(access_token="exchanged-token")


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
      self,
      client_info: object,
      refresh_token:
      object,
      scopes: list[str]
    ) -> OAuthToken:
        return OAuthToken(access_token="refreshed-token")


class DummyRequest:
    def __init__(self, data: Mapping[str, str | None]) -> None:
        self._data = dict(data)

    async def form(self) -> dict[str, str | None]:
        return dict(self._data)


@pytest.mark.anyio
async def test_handle_authorization_code_with_implicit_redirect() -> None:
    code_verifier = "a" * 64
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    provider = AuthorizationCodeProvider(expected_code="auth-code", code_challenge=code_challenge)
    client_info = OAuthClientInformationFull(client_id="client", grant_types=["authorization_code"])
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

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
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

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
async def test_handle_route_authorization_code_branch() -> None:
    code_verifier = "a" * 64
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    provider = AuthorizationCodeProvider(expected_code="auth-code", code_challenge=code_challenge)
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["authorization_code"],
        scope="alpha",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    request_data = {
        "grant_type": "authorization_code",
        "code": "auth-code",
        "redirect_uri": None,
        "client_id": "client",
        "client_secret": "secret",
        "code_verifier": code_verifier,
    }

    response = await handler.handle(cast(Request, DummyRequest(request_data)))

    assert response.status_code == 200
    payload = json.loads(bytes(response.body).decode())
    assert payload["access_token"] == "auth-token"


@pytest.mark.anyio
async def test_handle_route_client_credentials_branch() -> None:
    provider = ClientCredentialsProviderSuccess()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["client_credentials"],
        scope="alpha beta",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    request_data = {
        "grant_type": "client_credentials",
        "scope": "beta",
        "client_id": "client",
        "client_secret": "secret",
    }

    response = await handler.handle(cast(Request, DummyRequest(request_data)))

    assert response.status_code == 200
    payload = json.loads(bytes(response.body).decode())
    assert payload["access_token"] == "client-token"
    assert provider.last_scopes == ["beta"]


@pytest.mark.anyio
async def test_handle_route_refresh_token_branch() -> None:
    provider = RefreshTokenProvider()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["refresh_token"],
        scope="alpha",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    request_data = {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token",
        "scope": "alpha",
        "client_id": "client",
        "client_secret": "secret",
    }

    response = await handler.handle(cast(Request, DummyRequest(request_data)))

    assert response.status_code == 200
    body = response.body
    assert isinstance(body, bytes | bytearray | memoryview)
    payload = json.loads(bytes(body).decode())
    assert payload["access_token"] == "refreshed-token"


@pytest.mark.anyio
async def test_handle_route_refresh_token_invalid_scope() -> None:
    provider = RefreshTokenProvider()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["refresh_token"],
        scope="alpha",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    request_data = {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token",
        "scope": "beta",
        "client_id": "client",
        "client_secret": "secret",
    }

    response = await handler.handle(cast(Request, DummyRequest(request_data)))

    assert response.status_code == 400
    payload = json.loads(bytes(response.body).decode())
    assert payload == {
        "error": "invalid_scope",
        "error_description": "cannot request scope `beta` not provided by refresh token",
    }


@pytest.mark.anyio
async def test_handle_route_refresh_token_dispatches_to_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RefreshTokenProvider()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["refresh_token"],
        scope="alpha",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    captured_requests: list[RefreshTokenRequest] = []

    async def fake_handle_refresh_token(
        self: TokenHandler,
        client: OAuthClientInformationFull,
        token_request: RefreshTokenRequest,
    ) -> TokenSuccessResponse:
        captured_requests.append(token_request)
        return TokenSuccessResponse(root=OAuthToken(access_token="dispatched-token"))

    monkeypatch.setattr(
        handler,
        "_handle_refresh_token",
        MethodType(fake_handle_refresh_token, handler),
    )

    request_data = {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token",
        "client_id": "client",
        "client_secret": "secret",
    }

    response = await handler.handle(cast(Request, DummyRequest(request_data)))

    assert response.status_code == 200
    assert captured_requests
    assert isinstance(captured_requests[0], RefreshTokenRequest)


@pytest.mark.anyio
async def test_handle_route_refresh_token_unrecognized_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RefreshTokenProvider()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["mystery"],
        scope="alpha",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    class UnknownRequest:
        grant_type = "mystery"
        client_id = "client"
        client_secret = "secret"

    unknown_request = UnknownRequest()

    def fake_model_validate(
      cls: type[TokenRequest],
      data: dict[str, object]
    ) -> SimpleNamespace:  # type: ignore[unused-argument]
        return SimpleNamespace(root=unknown_request)

    monkeypatch.setattr(TokenRequest, "model_validate", classmethod(fake_model_validate))

    request_data = {
        "grant_type": "mystery",
        "client_id": "client",
        "client_secret": "secret",
    }

    with pytest.raises(UnboundLocalError):
        await handler.handle(cast(Request, DummyRequest(request_data)))


@pytest.mark.anyio
async def test_handle_route_token_exchange_branch() -> None:
    provider = TokenExchangeProviderStub()
    client_info = OAuthClientInformationFull(
        client_id="client",
        grant_types=["token_exchange"],
        scope="alpha beta",
    )
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=cast(ClientAuthenticator, DummyAuthenticator(client_info)),
    )

    request_data = {
        "grant_type": "token_exchange",
        "subject_token": "subject-token",
        "subject_token_type": "access_token",
        "actor_token": "actor-token",
        "actor_token_type": "jwt",
        "scope": "alpha beta",
        "audience": "https://audience.example.com",
        "resource": "https://resource.example.com",
        "client_id": "client",
        "client_secret": "secret",
    }

    response = await handler.handle(cast(Request, DummyRequest(request_data)))

    assert response.status_code == 200
    payload = json.loads(bytes(response.body).decode())
    assert payload["access_token"] == "exchanged-token"
    assert provider.last_call == {
        "subject_token": "subject-token",
        "subject_token_type": "access_token",
        "actor_token": "actor-token",
        "actor_token_type": "jwt",
        "scopes": ["alpha", "beta"],
        "audience": "https://audience.example.com",
        "resource": "https://resource.example.com",
    }
