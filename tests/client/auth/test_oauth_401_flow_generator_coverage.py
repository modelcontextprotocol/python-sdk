"""Coverage tests for oauth_401_flow_generator and Protocol stubs.

These tests intentionally exercise Protocol method bodies (``...``) to satisfy branch coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest
from pydantic import AnyHttpUrl

import mcp.client.auth._oauth_401_flow as _oauth_401_flow
from mcp.client.auth._oauth_401_flow import _OAuth401FlowProvider, oauth_401_flow_generator, oauth_403_flow_generator
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.multi_protocol import _OAuthTokenOnlyStorage
from mcp.client.auth.protocol import (
    AuthContext,
    AuthProtocol,
    DPoPEnabledProtocol,
    DPoPProofGenerator,
    DPoPStorage,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken, ProtectedResourceMetadata


class _NoopStorage:
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        return None


@dataclass
class _DummyOAuthContext:
    server_url: str
    client_metadata: OAuthClientMetadata
    storage: Any
    client_metadata_url: str | None = None
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: Any = None
    auth_server_url: str | None = None
    client_info: OAuthClientInformationFull | None = None

    def get_authorization_base_url(self, server_url: str) -> str:
        return server_url.rstrip("/")


class _DummyProvider:
    def __init__(self, ctx: _DummyOAuthContext) -> None:
        self.context = ctx
        self._token_request = httpx.Request("POST", "https://as.example/token")

    async def _perform_authorization(self) -> httpx.Request:
        return self._token_request

    async def _handle_token_response(self, response: httpx.Response) -> None:
        await response.aread()


def _prm(*, auth_server: str) -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata.model_validate(
        {
            "resource": "https://rs.example/mcp",
            "authorization_servers": [auth_server],
            "scopes_supported": ["read"],
        }
    )


def _oauth_metadata_response(*, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=b"""{
          "issuer": "https://as.example",
          "authorization_endpoint": "https://as.example/authorize",
          "token_endpoint": "https://as.example/token"
        }""",
        request=request,
    )


@pytest.mark.anyio
async def test_dummy_context_and_storage_helpers_are_exercised_for_coverage() -> None:
    storage = _NoopStorage()
    await storage.set_client_info(
        OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/cb")])
    )
    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost/cb")], client_name="t"),
        storage=storage,
    )
    assert ctx.get_authorization_base_url("https://example.com/x/") == "https://example.com/x"


@pytest.mark.anyio
async def test_oauth_401_flow_generator_initial_prm_sets_auth_server_url() -> None:
    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost/cb")], client_name="t"),
        storage=_NoopStorage(),
        client_info=OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/cb")]),
    )
    provider = _DummyProvider(ctx)

    request = httpx.Request("GET", "https://rs.example/mcp")
    response_401 = httpx.Response(401, headers={"WWW-Authenticate": 'Bearer scope="read"'}, request=request)

    flow = oauth_401_flow_generator(provider, request, response_401, initial_prm=_prm(auth_server="https://as.example"))
    oauth_metadata_req = await flow.__anext__()

    assert ctx.auth_server_url == "https://as.example/"

    token_req = await flow.asend(_oauth_metadata_response(request=oauth_metadata_req))
    assert token_req.method == "POST"

    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200, content=b"{}", request=token_req))


@pytest.mark.anyio
async def test_oauth_401_flow_generator_initial_prm_without_authorization_servers_uses_legacy_oasm_discovery() -> None:
    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost/cb")], client_name="t"),
        storage=_NoopStorage(),
        client_info=OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/cb")]),
    )
    provider = _DummyProvider(ctx)

    request = httpx.Request("GET", "https://rs.example/mcp")
    response_401 = httpx.Response(401, headers={"WWW-Authenticate": 'Bearer scope="read"'}, request=request)
    prm = ProtectedResourceMetadata.model_construct(
        resource="https://rs.example/mcp",
        authorization_servers=[],
    )

    flow = oauth_401_flow_generator(provider, request, response_401, initial_prm=prm)
    oauth_metadata_req = await flow.__anext__()
    token_req = await flow.asend(_oauth_metadata_response(request=oauth_metadata_req))

    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200, content=b"{}", request=token_req))


@pytest.mark.anyio
async def test_oauth_401_flow_generator_breaks_oasm_discovery_on_server_error() -> None:
    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost/cb")], client_name="t"),
        storage=_NoopStorage(),
        client_info=OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/cb")]),
    )
    provider = _DummyProvider(ctx)

    request = httpx.Request("GET", "https://rs.example/mcp")
    response_401 = httpx.Response(401, headers={"WWW-Authenticate": 'Bearer scope="read"'}, request=request)

    flow = oauth_401_flow_generator(provider, request, response_401, initial_prm=_prm(auth_server="https://as.example"))
    oauth_metadata_req = await flow.__anext__()

    token_req = await flow.asend(httpx.Response(500, request=oauth_metadata_req))
    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200, content=b"{}", request=token_req))


@pytest.mark.anyio
async def test_oauth_401_flow_generator_client_credentials_requires_client_info() -> None:
    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(
            redirect_uris=[AnyHttpUrl("http://localhost/cb")],
            client_name="t",
            grant_types=["client_credentials"],
        ),
        storage=_NoopStorage(),
        client_info=None,
    )
    provider = _DummyProvider(ctx)

    request = httpx.Request("GET", "https://rs.example/mcp")
    response_401 = httpx.Response(401, headers={"WWW-Authenticate": 'Bearer scope="read"'}, request=request)

    flow = oauth_401_flow_generator(provider, request, response_401, initial_prm=_prm(auth_server="https://as.example"))
    oauth_metadata_req = await flow.__anext__()

    with pytest.raises(OAuthFlowError):
        await flow.asend(_oauth_metadata_response(request=oauth_metadata_req))


@pytest.mark.anyio
async def test_oauth_403_flow_generator_exits_when_error_is_not_insufficient_scope() -> None:
    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost/cb")], client_name="t"),
        storage=_NoopStorage(),
        client_info=OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/cb")]),
    )
    provider = _DummyProvider(ctx)

    request = httpx.Request("GET", "https://rs.example/mcp")
    response_403 = httpx.Response(403, headers={"WWW-Authenticate": 'Bearer error="access_denied"'}, request=request)

    flow = oauth_403_flow_generator(provider, request, response_403)
    with pytest.raises(StopAsyncIteration):
        await flow.__anext__()


@pytest.mark.anyio
async def test_oauth_401_flow_generator_skips_oasm_loop_when_discovery_urls_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_urls(auth_server_url: str | None, server_url: str) -> list[str]:
        return []

    monkeypatch.setattr(_oauth_401_flow, "build_oauth_authorization_server_metadata_discovery_urls", build_urls)

    ctx = _DummyOAuthContext(
        server_url="https://rs.example/mcp",
        client_metadata=OAuthClientMetadata(redirect_uris=[AnyHttpUrl("http://localhost/cb")], client_name="t"),
        storage=_NoopStorage(),
        client_info=OAuthClientInformationFull(client_id="cid", redirect_uris=[AnyHttpUrl("http://localhost/cb")]),
    )
    provider = _DummyProvider(ctx)

    request = httpx.Request("GET", "https://rs.example/mcp")
    response_401 = httpx.Response(401, headers={"WWW-Authenticate": 'Bearer scope="read"'}, request=request)

    flow = oauth_401_flow_generator(provider, request, response_401, initial_prm=_prm(auth_server="https://as.example"))
    token_req = await flow.__anext__()

    assert token_req.method == "POST"
    with pytest.raises(StopAsyncIteration):
        await flow.asend(httpx.Response(200, content=b"{}", request=token_req))


@pytest.mark.anyio
async def test_protocol_stub_bodies_are_executable_for_branch_coverage() -> None:
    # _oauth_401_flow._OAuth401FlowProvider Protocol stubs
    context_property = getattr(_OAuth401FlowProvider, "context")
    assert context_property.fget is not None
    context_fget = context_property.fget
    assert context_fget(object()) is None
    perform_authorization = getattr(_OAuth401FlowProvider, "_perform_authorization")
    assert await perform_authorization(object()) is None
    handle_token_response = getattr(_OAuth401FlowProvider, "_handle_token_response")
    assert await handle_token_response(object(), httpx.Response(200)) is None

    # protocol.py Protocol stubs
    get_key_pair = cast(Any, DPoPStorage.get_key_pair)
    assert await get_key_pair(object(), "oauth2") is None
    set_key_pair = cast(Any, DPoPStorage.set_key_pair)
    assert await set_key_pair(object(), "oauth2", object()) is None

    # multi_protocol.py Protocol stubs (single-line "..." bodies are not excluded by coverage config)
    get_tokens = cast(Any, _OAuthTokenOnlyStorage.get_tokens)
    assert await get_tokens(object()) is None
    set_tokens = cast(Any, _OAuthTokenOnlyStorage.set_tokens)
    assert await set_tokens(object(), OAuthToken(access_token="at", token_type="Bearer")) is None

    generate_proof = cast(Any, DPoPProofGenerator.generate_proof)
    assert generate_proof(object(), "GET", "https://example.com") is None
    get_public_key_jwk = cast(Any, DPoPProofGenerator.get_public_key_jwk)
    assert get_public_key_jwk(object()) is None

    auth_context = AuthContext(server_url="https://example.com", storage=object(), protocol_id="x")
    authenticate = cast(Any, AuthProtocol.authenticate)
    assert await authenticate(object(), auth_context) is None
    prepare_request = cast(Any, AuthProtocol.prepare_request)
    assert prepare_request(object(), httpx.Request("GET", "https://example.com"), object()) is None
    validate_credentials = cast(Any, AuthProtocol.validate_credentials)
    assert validate_credentials(object(), object()) is None
    discover_metadata = cast(Any, AuthProtocol.discover_metadata)
    assert await discover_metadata(object(), None) is None

    supports_dpop = cast(Any, DPoPEnabledProtocol.supports_dpop)
    assert supports_dpop(object()) is None
    get_dpop_proof_generator = cast(Any, DPoPEnabledProtocol.get_dpop_proof_generator)
    assert get_dpop_proof_generator(object()) is None
    initialize_dpop = cast(Any, DPoPEnabledProtocol.initialize_dpop)
    assert await initialize_dpop(object()) is None
