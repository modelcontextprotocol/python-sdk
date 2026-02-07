"""Coverage tests for TokenHandler client_credentials flow."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import AnyHttpUrl
from starlette.requests import Request

from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class _ProviderBase:
    def __init__(self, client: OAuthClientInformationFull) -> None:
        self._client = client

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._client if client_id == self._client.client_id else None


class _ProviderWithClientCredentials(_ProviderBase):
    async def exchange_client_credentials(
        self,
        client_info: OAuthClientInformationFull,
        *,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        scope_str = " ".join(scopes) if scopes else None
        return OAuthToken(access_token="at", token_type="Bearer", expires_in=3600, scope=scope_str)


class _ProviderWithoutClientCredentials(_ProviderBase):
    pass


class _ProviderWithClientCredentialsError(_ProviderBase):
    async def exchange_client_credentials(
        self,
        client_info: OAuthClientInformationFull,
        *,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        raise TokenError(error="invalid_scope", error_description="bad scope")


class _ProviderWithClientCredentialsNone(_ProviderBase):
    async def exchange_client_credentials(
        self,
        client_info: OAuthClientInformationFull,
        *,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken | None:
        return None


def _make_form_request(body: bytes) -> Request:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/token",
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
        ],
    }
    return Request(scope, receive)


def _client_info(*, grant_types: list[str]) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="cid",
        client_secret="sec",
        token_endpoint_auth_method="client_secret_post",
        redirect_uris=[AnyHttpUrl("http://localhost/callback")],
        grant_types=grant_types,
    )


@pytest.mark.anyio
async def test_token_handler_client_credentials_success() -> None:
    provider = _ProviderWithClientCredentials(_client_info(grant_types=["client_credentials"]))
    authenticator = ClientAuthenticator(cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider))
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=authenticator,
    )
    request = _make_form_request(b"grant_type=client_credentials&client_id=cid&client_secret=sec&scope=read")

    response = await handler.handle(request)

    assert response.status_code == 200


@pytest.mark.anyio
async def test_token_handler_client_credentials_unsupported_when_provider_missing_exchange() -> None:
    provider = _ProviderWithoutClientCredentials(_client_info(grant_types=["client_credentials"]))
    authenticator = ClientAuthenticator(cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider))
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=authenticator,
    )
    request = _make_form_request(b"grant_type=client_credentials&client_id=cid&client_secret=sec")

    response = await handler.handle(request)

    assert response.status_code == 400


@pytest.mark.anyio
async def test_token_handler_client_credentials_surfaces_token_error() -> None:
    provider = _ProviderWithClientCredentialsError(_client_info(grant_types=["client_credentials"]))
    authenticator = ClientAuthenticator(cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider))
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=authenticator,
    )
    request = _make_form_request(b"grant_type=client_credentials&client_id=cid&client_secret=sec&scope=bad")

    response = await handler.handle(request)

    assert response.status_code == 400


@pytest.mark.anyio
async def test_token_handler_client_credentials_uses_client_scope_when_request_scope_missing() -> None:
    client = OAuthClientInformationFull(
        client_id="cid",
        client_secret="sec",
        token_endpoint_auth_method="client_secret_post",
        redirect_uris=[AnyHttpUrl("http://localhost/callback")],
        grant_types=["client_credentials"],
        scope="read write",
    )
    provider = _ProviderWithClientCredentials(client)
    authenticator = ClientAuthenticator(cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider))
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=authenticator,
    )
    request = _make_form_request(b"grant_type=client_credentials&client_id=cid&client_secret=sec")

    response = await handler.handle(request)

    assert response.status_code == 200
    assert response.body is not None
    assert b'"scope":"read write"' in response.body


@pytest.mark.anyio
async def test_token_handler_client_credentials_returns_error_when_exchange_returns_none() -> None:
    provider = _ProviderWithClientCredentialsNone(_client_info(grant_types=["client_credentials"]))
    authenticator = ClientAuthenticator(cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider))
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=authenticator,
    )
    request = _make_form_request(b"grant_type=client_credentials&client_id=cid&client_secret=sec")

    response = await handler.handle(request)

    assert response.status_code == 400


@pytest.mark.anyio
async def test_token_handler_falls_through_when_token_request_is_unexpected(monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp.server.auth.handlers.token as token_module

    provider = _ProviderWithClientCredentials(_client_info(grant_types=["client_credentials"]))
    authenticator = ClientAuthenticator(cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider))
    handler = TokenHandler(
        provider=cast(OAuthAuthorizationServerProvider[Any, Any, Any], provider),
        client_authenticator=authenticator,
    )

    class _WeirdTokenRequest:
        grant_type = "client_credentials"

    def validate_python(_: object) -> _WeirdTokenRequest:
        return _WeirdTokenRequest()

    monkeypatch.setattr(token_module.token_request_adapter, "validate_python", validate_python)

    request = _make_form_request(b"grant_type=client_credentials&client_id=cid&client_secret=sec")
    response = await handler.handle(request)

    assert response.status_code == 400
