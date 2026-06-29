"""Regression test for #1630: OAuth2 scope was incorrectly set to the resource_metadata URL from WWW-Authenticate."""

from unittest import mock

import httpx
import pytest
from pydantic import AnyUrl

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)


class MockTokenStorage:
    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens  # pragma: no cover

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info  # pragma: no cover

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info  # pragma: no cover


@pytest.mark.anyio
async def test_401_uses_www_auth_scope_not_resource_metadata_url():
    async def redirect_handler(url: str) -> None:
        pass  # pragma: no cover

    async def callback_handler() -> AuthorizationCodeResult:
        return AuthorizationCodeResult(code="test_auth_code", state="test_state")  # pragma: no cover

    client_metadata = OAuthClientMetadata(
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
        client_name="Test Client",
    )

    provider = OAuthClientProvider(
        server_url="https://api.example.com/mcp",
        client_metadata=client_metadata,
        storage=MockTokenStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    provider.context.current_tokens = None
    provider.context.token_expiry_time = None
    provider._initialized = True

    # Pre-set client info to skip DCR
    provider.context.client_info = OAuthClientInformationFull(
        client_id="test_client",
        redirect_uris=[AnyUrl("http://localhost:3030/callback")],
    )

    test_request = httpx.Request("GET", "https://api.example.com/mcp")
    auth_flow = provider.async_auth_flow(test_request)

    await auth_flow.__anext__()

    # WWW-Authenticate carries both resource_metadata and scope; the bug used the URL as the scope
    resource_metadata_url = "https://api.example.com/.well-known/oauth-protected-resource"
    expected_scope = "read write"

    response_401 = httpx.Response(
        401,
        headers={"WWW-Authenticate": (f'Bearer resource_metadata="{resource_metadata_url}", scope="{expected_scope}"')},
        request=test_request,
    )

    prm_request = await auth_flow.asend(response_401)
    assert ".well-known/oauth-protected-resource" in str(prm_request.url)

    # scopes_supported must lose to the WWW-Authenticate scope
    prm_response = httpx.Response(
        200,
        content=(
            b'{"resource": "https://api.example.com/mcp", '
            b'"authorization_servers": ["https://auth.example.com"], '
            b'"scopes_supported": ["fallback:scope1", "fallback:scope2"]}'
        ),
        request=prm_request,
    )

    oauth_metadata_request = await auth_flow.asend(prm_response)
    assert ".well-known/oauth-authorization-server" in str(oauth_metadata_request.url)

    oauth_metadata_response = httpx.Response(
        200,
        content=(
            b'{"issuer": "https://auth.example.com", '
            b'"authorization_endpoint": "https://auth.example.com/authorize", '
            b'"token_endpoint": "https://auth.example.com/token"}'
        ),
        request=oauth_metadata_request,
    )

    # Mock authorization to skip interactive flow
    provider._perform_authorization_code_grant = mock.AsyncMock(return_value=("test_auth_code", "test_code_verifier"))

    token_request = await auth_flow.asend(oauth_metadata_response)
    assert "token" in str(token_request.url)

    actual_scope = provider.context.client_metadata.scope

    assert actual_scope == expected_scope, (
        f"Expected scope to be '{expected_scope}' from WWW-Authenticate header, "
        f"but got '{actual_scope}'. "
        f"If scope is '{resource_metadata_url}', the bug from #1630 is present."
    )

    assert actual_scope != resource_metadata_url, (
        f"BUG #1630: Scope was incorrectly set to resource_metadata URL '{resource_metadata_url}' "
        f"instead of the actual scope '{expected_scope}'"
    )

    # Complete the flow to properly release the lock
    token_response = httpx.Response(
        200,
        content=b'{"access_token": "test_token", "token_type": "Bearer", "expires_in": 3600}',
        request=token_request,
    )

    final_request = await auth_flow.asend(token_response)
    assert final_request.headers["Authorization"] == "Bearer test_token"

    final_response = httpx.Response(200, request=final_request)
    try:
        await auth_flow.asend(final_response)
    except StopAsyncIteration:
        pass
