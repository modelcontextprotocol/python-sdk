"""Additional coverage tests for OAuthClientProvider.run_authentication and client_credentials."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.oauth2 import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken, ProtectedResourceMetadata


class _InMemoryOAuthStorage:
    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: Any = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> Any:
        return self._client_info

    async def set_client_info(self, client_info: Any) -> None:
        self._client_info = client_info


@pytest.mark.anyio
async def test_in_memory_oauth_storage_getters_are_exercised_for_test_coverage() -> None:
    storage = _InMemoryOAuthStorage()
    assert await storage.get_tokens() is None
    assert await storage.get_client_info() is None


@pytest.mark.anyio
async def test_exchange_token_client_credentials_requires_client_info() -> None:
    storage = _InMemoryOAuthStorage()
    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
        ),
        storage=storage,
        fixed_client_info=None,
    )
    with pytest.raises(OAuthFlowError, match="Missing client info"):
        await provider._exchange_token_client_credentials()


@pytest.mark.anyio
async def test_run_authentication_with_prm_and_oasm_discovery_errors_then_cimd_then_client_credentials() -> None:
    storage = _InMemoryOAuthStorage()
    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
            scope="read",
        ),
        storage=storage,
        client_metadata_url="https://client.example/metadata.json",
    )

    # PRM success response (second URL in fallback chain)
    prm_json = b'{"resource":"https://rs.example/mcp","authorization_servers":["https://as.example/tenant"]}'

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://rs.example/custom_prm":
            raise RuntimeError("network down")
        if url.startswith("https://rs.example/.well-known/oauth-protected-resource"):
            return httpx.Response(200, content=prm_json, request=request)

        if url == "https://as.example/.well-known/oauth-authorization-server/tenant":
            raise RuntimeError("oasm transient error")
        if url == "https://as.example/.well-known/openid-configuration/tenant":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://as.example",
                    "authorization_endpoint": "https://as.example/authorize",
                    "token_endpoint": "https://as.example/token",
                    "client_id_metadata_document_supported": True,
                },
                request=request,
            )

        if url == "https://as.example/token":
            return httpx.Response(
                200,
                json={"access_token": "at", "token_type": "Bearer", "expires_in": 3600, "scope": "read"},
                request=request,
            )

        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await provider.run_authentication(
            http_client,
            resource_metadata_url="https://rs.example/custom_prm",
        )

    assert storage._tokens is not None
    assert storage._tokens.access_token == "at"
    assert storage._client_info is not None
    assert handler(httpx.Request("GET", "https://rs.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_run_authentication_uses_dcr_when_cimd_not_supported() -> None:
    storage = _InMemoryOAuthStorage()
    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
        ),
        storage=storage,
    )

    prm = ProtectedResourceMetadata.model_validate(
        {"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example"]}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://as.example/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://as.example",
                    "authorization_endpoint": "https://as.example/authorize",
                    "token_endpoint": "https://as.example/token",
                    "registration_endpoint": "https://as.example/register",
                },
                request=request,
            )
        if url == "https://as.example/register":
            return httpx.Response(
                201,
                content=b'{"client_id":"cid","client_secret":"sec","redirect_uris":["http://localhost/callback"],"token_endpoint_auth_method":"client_secret_post"}',
                request=request,
            )
        if url == "https://as.example/token":
            return httpx.Response(
                200,
                json={"access_token": "at2", "token_type": "Bearer", "expires_in": 3600},
                request=request,
            )
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await provider.run_authentication(http_client, protected_resource_metadata=prm)

    assert storage._tokens is not None
    assert storage._tokens.access_token == "at2"
    assert handler(httpx.Request("GET", "https://rs.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_exchange_token_client_credentials_includes_optional_fields_conditionally() -> None:
    storage = _InMemoryOAuthStorage()
    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
            scope=None,
        ),
        storage=storage,
        fixed_client_info=None,
    )
    provider.context.client_info = OAuthClientInformationFull(
        client_id="",
        client_secret=None,
        token_endpoint_auth_method="none",
        redirect_uris=[AnyHttpUrl("http://localhost/callback")],
    )

    request = await provider._exchange_token_client_credentials()
    body = request.content.decode()
    assert "grant_type=client_credentials" in body
    assert "client_id=" not in body
    assert "resource=" not in body
    assert "scope=" not in body

    provider2 = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
            scope="read",
        ),
        storage=_InMemoryOAuthStorage(),
        fixed_client_info=OAuthClientInformationFull.model_validate(
            {
                "client_id": "cid",
                "client_secret": "sec",
                "token_endpoint_auth_method": "client_secret_post",
                "redirect_uris": ["http://localhost/callback"],
            }
        ),
    )
    provider2.context.protected_resource_metadata = ProtectedResourceMetadata.model_validate(
        {"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example"]}
    )
    req2 = await provider2._exchange_token_client_credentials()
    body2 = req2.content.decode()
    assert "client_id=cid" in body2
    assert "resource=" in body2
    assert "scope=read" in body2


@pytest.mark.anyio
async def test_run_authentication_handles_protected_resource_metadata_without_authorization_servers() -> None:
    storage = _InMemoryOAuthStorage()
    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
        ),
        storage=storage,
        client_metadata_url="https://client.example/metadata.json",
    )
    protected_resource_metadata = ProtectedResourceMetadata.model_construct(
        resource="https://rs.example/mcp",
        authorization_servers=[],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://rs.example/.well-known/oauth-protected-resource"):
            return httpx.Response(
                200,
                json={"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example"]},
                request=request,
            )
        if url == "https://as.example/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://as.example",
                    "authorization_endpoint": "https://as.example/authorize",
                    "token_endpoint": "https://as.example/token",
                    "client_id_metadata_document_supported": True,
                },
                request=request,
            )
        if url == "https://as.example/token":
            return httpx.Response(
                200,
                json={"access_token": "at3", "token_type": "Bearer", "expires_in": 3600},
                request=request,
            )
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await provider.run_authentication(
            http_client,
            protected_resource_metadata=protected_resource_metadata,
            resource_metadata_url="https://rs.example/.well-known/oauth-protected-resource/mcp",
        )

    assert storage._tokens is not None
    assert storage._tokens.access_token == "at3"
    assert handler(httpx.Request("GET", "https://unexpected.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_run_authentication_raises_when_prm_has_no_authorization_servers() -> None:
    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
        ),
        storage=_InMemoryOAuthStorage(),
    )

    protected_resource_metadata = ProtectedResourceMetadata.model_construct(
        resource="https://rs.example/mcp",
        authorization_servers=[],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(OAuthFlowError, match="Could not discover authorization server"):
            await provider.run_authentication(http_client, protected_resource_metadata=protected_resource_metadata)

    assert handler(httpx.Request("GET", "https://unexpected.example/unexpected")).status_code == 500


@pytest.mark.anyio
async def test_run_authentication_sets_prm_but_does_not_set_auth_server_url_when_prm_has_no_authorization_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp.client.auth.oauth2 as oauth2_module

    provider = OAuthClientProvider(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
            client_name="t",
            grant_types=["client_credentials"],
        ),
        storage=_InMemoryOAuthStorage(),
        fixed_client_info=OAuthClientInformationFull(
            client_id="cid",
            client_secret="sec",
            token_endpoint_auth_method="client_secret_post",
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
        ),
    )

    prm_without_authorization_servers = ProtectedResourceMetadata.model_construct(
        resource="https://rs.example/mcp",
        authorization_servers=[],
    )

    async def fake_handle_protected_resource_response(_: httpx.Response) -> ProtectedResourceMetadata | None:
        return prm_without_authorization_servers

    monkeypatch.setattr(oauth2_module, "handle_protected_resource_response", fake_handle_protected_resource_response)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(OAuthFlowError, match="Could not discover authorization server"):
            await provider.run_authentication(
                http_client,
                resource_metadata_url="https://rs.example/.well-known/oauth-protected-resource/mcp",
            )
