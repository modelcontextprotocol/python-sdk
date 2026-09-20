"""Direct tests for ClientAuthenticator's Basic-header client_id fallback."""

import base64

import pytest
from starlette.requests import Request

from mcp.server.auth.middleware.client_auth import (
    AuthenticationError,
    ClientAuthenticator,
)
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.shared.auth import OAuthClientInformationFull


class _StubProvider(OAuthAuthorizationServerProvider[None, None, None]):  # type: ignore[type-arg]
    def __init__(self, client: OAuthClientInformationFull | None):
        self._client = client

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if self._client and self._client.client_id == client_id:
            return self._client
        return None  # pragma: no cover

    async def register_client(self, client_info: OAuthClientInformationFull): ...  # pragma: no cover
    async def authorize(self, client: OAuthClientInformationFull, params): ...  # pragma: no cover


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="header-only-client",
        client_secret="s3cret",
        token_endpoint_auth_method="client_secret_basic",
        redirect_uris=["https://client.example.com/callback"],
        grant_types=["authorization_code"],
    )


def _request(body: bytes, auth_header: str | None) -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/token",
            "headers": headers,
        },
        receive=receive,
    )


@pytest.mark.anyio
async def test_basic_client_id_falls_back_to_authorization_header() -> None:
    """A client_secret_basic request with no body client_id authenticates via the header."""
    stored = _client()
    auth = ClientAuthenticator(_StubProvider(stored))
    creds = base64.b64encode(f"{stored.client_id}:{stored.client_secret}".encode()).decode()
    req = _request(b"grant_type=authorization_code&code=abc", f"Basic {creds}")

    result = await auth.authenticate_request(req)

    assert result.client_id == stored.client_id


@pytest.mark.anyio
async def test_no_credentials_anywhere_still_rejected() -> None:
    """With neither body nor header credentials, the original Missing client_id stands."""
    auth = ClientAuthenticator(_StubProvider(_client()))
    req = _request(b"grant_type=authorization_code&code=abc", None)

    with pytest.raises(AuthenticationError, match="Missing client_id"):
        await auth.authenticate_request(req)
