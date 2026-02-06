"""Additional coverage tests for MultiProtocolAuthProvider."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from pydantic import AnyHttpUrl

from mcp.client.auth.multi_protocol import (
    MultiProtocolAuthProvider,
    OAuthTokenStorageAdapter,
    TokenStorage,
    _credentials_to_storage,
    _oauth_token_to_credentials,
)
from mcp.client.auth.protocol import AuthContext, DPoPProofGenerator
from mcp.client.auth.protocols.oauth2 import OAuth2Protocol
from mcp.shared.auth import (
    APIKeyCredentials,
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthCredentials,
    OAuthToken,
    ProtectedResourceMetadata,
)


class _InMemoryDualStorage(TokenStorage):
    def __init__(self) -> None:
        self._tokens: AuthCredentials | OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


class _ApiKeyProtocol:
    protocol_id = "api_key"
    protocol_version = "1.0"

    def __init__(self, api_key: str, *, should_raise: bool = False) -> None:
        self._api_key = api_key
        self._should_raise = should_raise

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        if self._should_raise:
            raise RuntimeError("api_key auth failed")
        return APIKeyCredentials(protocol_id="api_key", api_key=self._api_key)

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        assert isinstance(credentials, APIKeyCredentials)
        request.headers["X-API-Key"] = credentials.api_key

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return isinstance(credentials, APIKeyCredentials) and bool(credentials.api_key)

    async def discover_metadata(
        self,
        metadata_url: str | None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


def test_oauth_token_to_credentials_leaves_expires_at_none_when_expires_in_missing() -> None:
    credentials = _oauth_token_to_credentials(OAuthToken(access_token="at", token_type="Bearer", expires_in=None))
    assert credentials.expires_at is None


@pytest.mark.anyio
async def test_helper_types_are_exercised_for_test_coverage() -> None:
    storage = _InMemoryDualStorage()
    assert await storage.get_client_info() is None
    info = OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/callback")])
    await storage.set_client_info(info)
    assert await storage.get_client_info() is info

    protocol = _ApiKeyProtocol("k")
    assert await protocol.discover_metadata(None) is None


def test_credentials_to_storage_calculates_expires_in(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1_700_000_000
    monkeypatch.setattr(time, "time", lambda: now)

    later = OAuthCredentials(
        protocol_id="oauth2",
        access_token="at",
        token_type="Bearer",
        refresh_token=None,
        scope=None,
        expires_at=now + 10,
    )
    out = _credentials_to_storage(later)
    assert isinstance(out, OAuthToken)
    assert out.expires_in == 10

    past = OAuthCredentials(
        protocol_id="oauth2",
        access_token="at",
        token_type="Bearer",
        refresh_token=None,
        scope=None,
        expires_at=now - 1,
    )
    out2 = _credentials_to_storage(past)
    assert isinstance(out2, OAuthToken)
    assert out2.expires_in == 0


@pytest.mark.anyio
async def test_parse_protocols_from_discovery_response_falls_back_to_prm_on_invalid_json() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])

    from mcp.shared.auth import ProtectedResourceMetadata

    prm_validated = ProtectedResourceMetadata.model_validate(
        {
            "resource": "https://rs.example/mcp",
            "authorization_servers": ["https://as.example/"],
            "mcp_auth_protocols": [{"protocol_id": "api_key", "protocol_version": "1.0"}],
        }
    )

    response = httpx.Response(200, content=b"{not-json", request=httpx.Request("GET", "https://rs/.well-known/x"))
    protocols = await provider._parse_protocols_from_discovery_response(response, prm_validated)
    assert [p.protocol_id for p in protocols] == ["api_key"]


@pytest.mark.anyio
async def test_parse_protocols_from_discovery_response_falls_back_to_prm_when_protocols_list_empty() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])

    prm_validated = ProtectedResourceMetadata.model_validate(
        {
            "resource": "https://rs.example/mcp",
            "authorization_servers": ["https://as.example/"],
            "mcp_auth_protocols": [{"protocol_id": "api_key", "protocol_version": "1.0"}],
        }
    )

    response = httpx.Response(
        200,
        json={"protocols": []},
        request=httpx.Request("GET", "https://rs/mcp/.well-known/authorization_servers"),
    )
    protocols = await provider._parse_protocols_from_discovery_response(response, prm_validated)
    assert [p.protocol_id for p in protocols] == ["api_key"]


@pytest.mark.anyio
async def test_handle_403_response_parses_fields() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])
    request = httpx.Request("GET", "https://rs.example/mcp")
    response = httpx.Response(
        403,
        headers={"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="read write"'},
        request=request,
    )
    await provider._handle_403_response(response, request)


@pytest.mark.anyio
async def test_handle_403_response_no_header_exits_early() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])
    request = httpx.Request("GET", "https://rs.example/mcp")
    response = httpx.Response(403, request=request)
    await provider._handle_403_response(response, request)


@pytest.mark.anyio
async def test_oauth_token_storage_adapter_does_not_persist_non_oauth_credentials() -> None:
    called: list[OAuthToken] = []

    class _Wrapped:
        async def get_tokens(self) -> OAuthToken | None:
            return None

        async def set_tokens(self, tokens: OAuthToken) -> None:
            called.append(tokens)

    adapter = OAuthTokenStorageAdapter(_Wrapped())
    assert await adapter.get_tokens() is None
    await adapter.set_tokens(APIKeyCredentials(protocol_id="api_key", api_key="k"))
    assert called == []
    token = OAuthToken(access_token="at", token_type="Bearer")
    await _Wrapped().set_tokens(token)
    assert called == [token]


class _DummyDpopGenerator:
    def __init__(self) -> None:
        self.seen_credential: str | None = "unset"

    def generate_proof(self, method: str, uri: str, credential: str | None = None, nonce: str | None = None) -> str:
        self.seen_credential = credential
        return "proof"

    def get_public_key_jwk(self) -> dict[str, Any]:
        return {"kty": "EC"}


class _DpopProtocolBase:
    protocol_version = "1.0"

    def __init__(self, protocol_id: str) -> None:
        self.protocol_id = protocol_id
        self.initialize_called = False

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        return APIKeyCredentials(protocol_id=self.protocol_id, api_key="k")

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        request.headers["x-auth"] = "ok"

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return True

    async def discover_metadata(
        self,
        metadata_url: str | None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None

    def supports_dpop(self) -> bool:
        return False

    def get_dpop_proof_generator(self) -> DPoPProofGenerator | None:
        return None

    async def initialize_dpop(self) -> None:
        self.initialize_called = True


@pytest.mark.anyio
async def test_ensure_dpop_initialized_skips_when_protocol_not_dpop_enabled() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[_ApiKeyProtocol("k")],
        dpop_enabled=True,
    )
    provider._initialize()
    await provider._ensure_dpop_initialized(APIKeyCredentials(protocol_id="api_key", api_key="k"))


@pytest.mark.anyio
async def test_ensure_dpop_initialized_skips_when_supports_dpop_false() -> None:
    storage = _InMemoryDualStorage()
    protocol = _DpopProtocolBase("oauth2")
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[protocol],
        dpop_enabled=True,
    )
    provider._initialize()

    await provider._ensure_dpop_initialized(OAuthCredentials(protocol_id="oauth2", access_token="at"))
    assert protocol.initialize_called is False


@pytest.mark.anyio
async def test_prepare_request_dpop_enabled_but_supports_dpop_false_does_not_set_dpop_header() -> None:
    storage = _InMemoryDualStorage()
    protocol = _DpopProtocolBase("oauth2")
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[protocol],
        dpop_enabled=True,
    )
    provider._initialize()

    request = httpx.Request("GET", "https://rs.example/mcp")
    provider._prepare_request(request, OAuthCredentials(protocol_id="oauth2", access_token="at"))
    assert "dpop" not in request.headers


@pytest.mark.anyio
async def test_prepare_request_dpop_enabled_generator_none_does_not_set_dpop_header() -> None:
    storage = _InMemoryDualStorage()

    class _NoGeneratorProtocol(_DpopProtocolBase):
        def supports_dpop(self) -> bool:
            return True

    protocol = _NoGeneratorProtocol("oauth2")
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[protocol],
        dpop_enabled=True,
    )
    provider._initialize()

    request = httpx.Request("GET", "https://rs.example/mcp")
    provider._prepare_request(request, OAuthCredentials(protocol_id="oauth2", access_token="at"))
    assert "dpop" not in request.headers


@pytest.mark.anyio
async def test_prepare_request_dpop_includes_proof_and_passes_none_credential_for_non_oauth_credentials() -> None:
    storage = _InMemoryDualStorage()
    generator = _DummyDpopGenerator()

    class _WithGeneratorProtocol(_DpopProtocolBase):
        def supports_dpop(self) -> bool:
            return True

        def get_dpop_proof_generator(self) -> Any:
            return generator

    protocol = _WithGeneratorProtocol("api_key")
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[protocol],
        dpop_enabled=True,
    )
    provider._initialize()

    request = httpx.Request("GET", "https://rs.example/mcp")
    provider._prepare_request(request, APIKeyCredentials(protocol_id="api_key", api_key="k"))
    assert request.headers["dpop"] == "proof"
    assert generator.seen_credential is None
    assert generator.get_public_key_jwk() == {"kty": "EC"}


@pytest.mark.anyio
async def test_dpop_protocol_base_helpers_are_exercised_for_test_coverage() -> None:
    protocol = _DpopProtocolBase("api_key")
    context = AuthContext(server_url="https://rs.example/mcp", storage=_InMemoryDualStorage(), protocol_id="api_key")
    credentials = await protocol.authenticate(context)
    assert protocol.validate_credentials(credentials) is True
    assert await protocol.discover_metadata(None) is None
    await protocol.initialize_dpop()
    assert protocol.initialize_called is True


@pytest.mark.anyio
async def test_async_auth_flow_returns_response_when_already_initialized() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])
    provider._initialize()

    request = httpx.Request("GET", "https://rs.example/mcp")
    flow = provider.async_auth_flow(request)
    yielded_request = await flow.__anext__()
    assert yielded_request is request
    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200, request=request))


@pytest.mark.anyio
async def test_401_flow_api_key_success_with_preferences_and_default_skips_uninjected() -> None:
    api_key = "k1"
    seen_api_key: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "oauth-protected-resource" in request.url.path:
            return httpx.Response(
                200,
                json={"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example/"]},
                request=request,
            )
        if request.method == "GET" and request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(
                200,
                json={"protocols": [{"protocol_id": "api_key", "protocol_version": "1.0"}]},
                request=request,
            )
        if request.method == "POST" and request.url.path == "/mcp":
            seen_api_key.append(request.headers.get("x-api-key"))
            if request.headers.get("x-api-key") == api_key:
                return httpx.Response(200, json={"ok": True}, request=request)
            www = (
                'Bearer error="invalid_token", '
                'resource_metadata="https://rs.example/.well-known/oauth-protected-resource/mcp", '
                'auth_protocols="oauth2 api_key", '
                'default_protocol="oauth2", '
                'protocol_preferences="api_key:1,oauth2:10"'
            )
            return httpx.Response(401, headers={"WWW-Authenticate": www}, request=request)
        return httpx.Response(404, request=request)

    storage = _InMemoryDualStorage()
    protocol = _ApiKeyProtocol(api_key)
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[protocol],
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        response = await client.post("https://rs.example/mcp", json={"ping": True})

    assert response.status_code == 200
    assert seen_api_key[0] is None
    assert api_key in seen_api_key
    assert handler(httpx.Request("GET", "https://rs.example/other")).status_code == 404


@pytest.mark.anyio
async def test_401_flow_api_key_failure_surfaces_last_auth_error() -> None:
    api_key = "k1"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "oauth-protected-resource" in request.url.path:
            return httpx.Response(
                200,
                json={"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example/"]},
                request=request,
            )
        if request.method == "GET" and request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(
                200,
                json={"protocols": [{"protocol_id": "api_key", "protocol_version": "1.0"}]},
                request=request,
            )
        if request.method == "POST" and request.url.path == "/mcp":
            www = (
                'Bearer error="invalid_token", '
                'resource_metadata="https://rs.example/.well-known/oauth-protected-resource/mcp", '
                'auth_protocols="api_key"'
            )
            return httpx.Response(401, headers={"WWW-Authenticate": www}, request=request)
        return httpx.Response(404, request=request)

    storage = _InMemoryDualStorage()
    protocol = _ApiKeyProtocol(api_key, should_raise=True)
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[protocol],
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        with pytest.raises(RuntimeError, match="api_key auth failed"):
            await client.post("https://rs.example/mcp", json={"ping": True})
    assert handler(httpx.Request("GET", "https://rs.example/other")).status_code == 404


@pytest.mark.anyio
async def test_401_flow_oauth2_fallback_via_prm_authorization_servers_client_credentials() -> None:
    storage = _InMemoryDualStorage()
    fixed_client_info = OAuthClientInformationFull(
        client_id="client",
        client_secret="secret",
        token_endpoint_auth_method="client_secret_post",
        redirect_uris=[AnyHttpUrl("http://localhost/callback")],
    )
    client_metadata = OAuthClientMetadata(
        redirect_uris=[AnyHttpUrl("http://localhost/callback")],
        client_name="t",
        grant_types=["client_credentials"],
    )
    oauth2 = OAuth2Protocol(
        client_metadata=client_metadata,
        fixed_client_info=fixed_client_info,
    )
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[oauth2],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "oauth-protected-resource" in request.url.path:
            return httpx.Response(
                200,
                json={"resource": "https://rs.example/mcp", "authorization_servers": ["https://as.example/"]},
                request=request,
            )
        if request.method == "GET" and request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(404, request=request)
        if request.method == "GET" and request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://as.example",
                    "authorization_endpoint": "https://as.example/authorize",
                    "token_endpoint": "https://as.example/token",
                },
                request=request,
            )
        if request.method == "POST" and request.url.path == "/token":
            return httpx.Response(
                200,
                json={"access_token": "at", "token_type": "Bearer", "expires_in": 3600},
                request=request,
            )
        if request.method == "POST" and request.url.path == "/mcp":
            if request.headers.get("authorization") == "Bearer at":
                return httpx.Response(200, json={"ok": True}, request=request)
            www = 'Bearer error="invalid_token", resource_metadata="https://rs.example/.well-known/oauth-protected-resource/mcp"'
            return httpx.Response(401, headers={"WWW-Authenticate": www}, request=request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        response = await client.post("https://rs.example/mcp", json={"ping": True})

    assert response.status_code == 200
    assert handler(httpx.Request("GET", "https://rs.example/other")).status_code == 404


@pytest.mark.anyio
async def test_async_auth_flow_handles_403_response() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(
        server_url="https://rs.example/mcp",
        storage=storage,
        protocols=[],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mcp":
            return httpx.Response(
                403,
                headers={"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="read"'},
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        response = await client.get("https://rs.example/mcp")

    assert response.status_code == 403
    assert handler(httpx.Request("GET", "https://rs.example/other")).status_code == 404


@pytest.mark.anyio
async def test_401_flow_no_hints_no_prm_no_protocols_retries_original_request() -> None:
    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])
    post_calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/mcp":
            post_calls.append(1)
            if len(post_calls) == 1:
                return httpx.Response(
                    401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}, request=request
                )
            return httpx.Response(200, json={"ok": True}, request=request)
        if request.method == "GET" and "oauth-protected-resource" in request.url.path:
            return httpx.Response(404, request=request)
        if request.method == "GET" and request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(200, json={"protocols": []}, request=request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=provider) as client:
        response = await client.post("https://rs.example/mcp", json={"ping": True})

    assert response.status_code == 200
    assert len(post_calls) == 2
    assert handler(httpx.Request("GET", "https://unexpected.example/other")).status_code == 404


@pytest.mark.anyio
async def test_401_flow_skips_prm_discovery_when_prm_urls_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp.client.auth.multi_protocol as multi_protocol_module

    def build_urls(www_auth_url: str | None, server_url: str) -> list[str]:
        return []

    monkeypatch.setattr(multi_protocol_module, "build_protected_resource_metadata_discovery_urls", build_urls)

    storage = _InMemoryDualStorage()
    provider = MultiProtocolAuthProvider(server_url="https://rs.example/mcp", storage=storage, protocols=[])
    request = httpx.Request("POST", "https://rs.example/mcp", json={"ping": True})

    flow = provider.async_auth_flow(request)
    yielded_request = await flow.__anext__()
    assert yielded_request is request

    discovery_request = await flow.asend(
        httpx.Response(401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}, request=request)
    )
    assert discovery_request.url.path.endswith("/mcp/.well-known/authorization_servers")

    retry_request = await flow.asend(httpx.Response(200, json={"protocols": []}, request=discovery_request))
    assert retry_request is request
    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200, json={"ok": True}, request=request))
