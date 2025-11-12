import base64
import time
from collections.abc import Iterator
from types import MethodType, SimpleNamespace, TracebackType
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import AnyUrl

from mcp.client.auth.oauth2 import (
    ClientCredentialsProvider,
    OAuthClientProvider,
    OAuthFlowError,
    TokenExchangeProvider,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)


class InMemoryStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class DummyAsyncClient:
    def __init__(
        self,
        *,
        send_responses: list[httpx.Response] | None = None,
        post_responses: list[httpx.Response] | None = None,
    ) -> None:
        self._send_responses = list(send_responses or [])
        self._post_responses = list(post_responses or [])

    async def __aenter__(self) -> "DummyAsyncClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None

    async def send(self, request: httpx.Request) -> httpx.Response:
        assert self._send_responses, "Unexpected send() call"
        return self._send_responses.pop(0)

    async def post(self, url: str, *, data: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        assert self._post_responses, "Unexpected post() call"
        return self._post_responses.pop(0)


class AsyncClientFactory:
    def __init__(self, clients: list[DummyAsyncClient]) -> None:
        self._clients: Iterator[DummyAsyncClient] = iter(clients)

    def __call__(self, *args: object, **kwargs: object) -> DummyAsyncClient:
        return next(self._clients)


def _redirect_uris() -> list[AnyUrl]:
    return cast(list[AnyUrl], ["https://client.example.com/callback"])


def _metadata_json() -> dict[str, object]:
    return {
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "registration_endpoint": "https://auth.example.com/register",
        "scopes_supported": ["alpha", "beta"],
    }


def _registration_json() -> dict[str, object]:
    return {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "redirect_uris": ["https://client.example.com/callback"],
        "grant_types": ["client_credentials"],
    }


def _token_json(scope: str = "alpha") -> dict[str, object]:
    return {
        "access_token": "access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": scope,
    }


def _make_response(status: int, *, json_data: dict[str, object] | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com")
    if json_data is None:
        return httpx.Response(status, request=request)
    return httpx.Response(status, json=json_data, request=request)


@pytest.mark.anyio
async def test_handle_oauth_metadata_response_sets_scope() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider(
        "https://api.example.com/service",
        metadata,
        storage,
    )

    response = _make_response(200, json_data=_metadata_json())

    await provider._handle_oauth_metadata_response(response)

    assert provider.client_metadata.scope == "alpha beta"
    assert provider._metadata is not None


@pytest.mark.anyio
async def test_client_credentials_initialize_loads_cached_values() -> None:
    storage = InMemoryStorage()
    stored_token = OAuthToken(access_token="cached-token")
    stored_client = OAuthClientInformationFull(client_id="cached-client")
    storage.tokens = stored_token
    storage.client_info = stored_client

    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    await provider.initialize()

    assert provider._current_tokens is stored_token
    assert provider._client_info is stored_client


def test_create_registration_request_uses_cached_client_info() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider(
        "https://api.example.com/service",
        metadata,
        storage,
    )

    provider._client_info = OAuthClientInformationFull(client_id="cached")

    assert provider._create_registration_request() is None


def test_create_registration_request_uses_context() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider(
        "https://api.example.com/service",
        metadata,
        storage,
    )

    oauth_metadata = OAuthMetadata.model_validate(_metadata_json())
    context_info = OAuthClientInformationFull(client_id="context-client")
    provider.context = SimpleNamespace(client_info=context_info)  # type: ignore[attr-defined]

    assert provider._create_registration_request(oauth_metadata) is None
    assert provider._client_info is context_info


def test_create_registration_request_builds_url_from_metadata() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider(
        "https://api.example.com/service",
        metadata,
        storage,
    )

    oauth_metadata = OAuthMetadata.model_validate(_metadata_json())
    request = provider._create_registration_request(oauth_metadata)
    assert request is not None
    assert str(request.url) == "https://auth.example.com/register"


def test_create_registration_request_builds_url_from_server() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider(
        "https://api.example.com/service/path",
        metadata,
        storage,
    )

    request = provider._create_registration_request(None)
    assert request is not None
    assert str(request.url) == "https://api.example.com/register"


def test_apply_client_auth_requires_client_id() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    with pytest.raises(OAuthFlowError):
        provider._apply_client_auth({}, {}, OAuthClientInformationFull(client_id=None))


def test_apply_client_auth_basic() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)
    provider._metadata = OAuthMetadata.model_validate(
        {**_metadata_json(), "token_endpoint_auth_methods_supported": ["client_secret_basic"]}
    )

    token_data: dict[str, str] = {}
    headers: dict[str, str] = {}
    client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")

    provider._apply_client_auth(token_data, headers, client_info)

    encoded = base64.b64encode(b"client:secret").decode()
    assert headers["Authorization"] == f"Basic {encoded}"
    assert "client_id" not in token_data


def test_apply_client_auth_basic_requires_secret() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)
    provider._metadata = OAuthMetadata.model_validate(
        {**_metadata_json(), "token_endpoint_auth_methods_supported": ["client_secret_basic"]}
    )

    with pytest.raises(OAuthFlowError):
        provider._apply_client_auth({}, {}, OAuthClientInformationFull(client_id="client", client_secret=None))


def test_apply_client_auth_post_method() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)
    provider._metadata = OAuthMetadata.model_validate(
        {**_metadata_json(), "token_endpoint_auth_methods_supported": ["client_secret_post"]}
    )

    token_data: dict[str, str] = {}
    headers: dict[str, str] = {}
    client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")

    provider._apply_client_auth(token_data, headers, client_info)

    assert token_data["client_id"] == "client"
    assert token_data["client_secret"] == "secret"
    assert "Authorization" not in headers


def test_apply_client_auth_prefers_post_when_supported() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)
    provider._metadata = OAuthMetadata.model_validate(
        {
            **_metadata_json(),
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        }
    )

    token_data: dict[str, str] = {}
    headers: dict[str, str] = {}
    client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")

    provider._apply_client_auth(token_data, headers, client_info)

    assert token_data["client_id"] == "client"
    assert token_data["client_secret"] == "secret"
    assert "Authorization" not in headers


def test_apply_client_auth_defaults_when_metadata_omits_supported_methods() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)
    provider._metadata = OAuthMetadata.model_validate(
        {**_metadata_json(), "token_endpoint_auth_methods_supported": ["none"]}
    )

    token_data: dict[str, str] = {}
    headers: dict[str, str] = {}
    client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")

    provider._apply_client_auth(token_data, headers, client_info)

    assert token_data == {"client_id": "client", "client_secret": "secret"}
    assert headers == {}


@pytest.mark.anyio
async def test_client_credentials_request_token_with_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    metadata_response = _make_response(200, json_data=_metadata_json())
    registration_response = _make_response(200, json_data=_registration_json())
    token_response = _make_response(200, json_data=_token_json())

    clients = [
        DummyAsyncClient(send_responses=[metadata_response]),
        DummyAsyncClient(send_responses=[registration_response]),
        DummyAsyncClient(post_responses=[token_response]),
    ]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    await provider._request_token()

    assert storage.tokens is not None
    assert storage.tokens.access_token == "access-token"
    assert provider._current_tokens is storage.tokens
    assert storage.client_info is not None
    assert provider.client_metadata.scope == "alpha beta"
    assert provider._token_expiry_time is not None and provider._token_expiry_time > time.time()


def test_client_credentials_has_valid_token_checks_expiry() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    provider._current_tokens = OAuthToken(access_token="token")
    provider._token_expiry_time = time.time() - 1

    assert not provider._has_valid_token()


@pytest.mark.anyio
async def test_client_credentials_validate_token_scopes_returns_when_missing() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    token = OAuthToken(access_token="token", scope=None)

    await provider._validate_token_scopes(token)


@pytest.mark.anyio
async def test_client_credentials_get_or_register_client(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    registration_response = _make_response(200, json_data=_registration_json())
    clients = [DummyAsyncClient(send_responses=[registration_response])]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    client_info = await provider._get_or_register_client()

    assert client_info.client_id == "client-id"
    assert storage.client_info is client_info


@pytest.mark.anyio
async def test_client_credentials_get_or_register_client_skips_request_when_not_needed() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    def fake_create_registration_request(
        self: ClientCredentialsProvider, metadata: OAuthMetadata | None
    ) -> httpx.Request | None:
        self._client_info = OAuthClientInformationFull(client_id="existing-client")
        return None

    provider._metadata = OAuthMetadata.model_validate(_metadata_json())
    provider._create_registration_request = MethodType(fake_create_registration_request, provider)

    client_info = await provider._get_or_register_client()

    assert client_info.client_id == "existing-client"


@pytest.mark.anyio
async def test_client_credentials_request_token_handles_invalid_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)

    metadata_responses = [
        _make_response(200, json_data={"issuer": "https://auth.example.com"}),
        _make_response(302),
    ]
    registration_response = _make_response(200, json_data=_registration_json())
    token_response = _make_response(200, json_data={"access_token": "access-token", "token_type": "Bearer"})

    clients = [
        DummyAsyncClient(send_responses=metadata_responses),
        DummyAsyncClient(send_responses=[registration_response]),
        DummyAsyncClient(post_responses=[token_response]),
    ]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    await provider._request_token()

    assert storage.tokens is not None
    assert storage.tokens.access_token == "access-token"
    assert provider._token_expiry_time is None


@pytest.mark.anyio
async def test_client_credentials_request_token_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")
    provider = ClientCredentialsProvider("https://api.example.com/service", metadata, storage)
    provider._metadata = OAuthMetadata.model_validate(_metadata_json())

    provider._client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")

    clients = [DummyAsyncClient(post_responses=[_make_response(400)])]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    with pytest.raises(Exception, match="Token request failed"):
        await provider._request_token()


@pytest.mark.anyio
async def test_client_credentials_request_token_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    metadata_responses = [_make_response(404) for _ in range(4)]
    registration_response = _make_response(200, json_data=_registration_json())
    token_response = _make_response(200, json_data=_token_json("alpha"))

    clients = [
        DummyAsyncClient(send_responses=metadata_responses),
        DummyAsyncClient(send_responses=[registration_response]),
        DummyAsyncClient(post_responses=[token_response]),
    ]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    await provider._request_token()

    assert storage.tokens is not None
    assert storage.tokens.scope == "alpha"
    assert provider._metadata is None


@pytest.mark.anyio
async def test_client_credentials_ensure_token_returns_when_valid() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)
    provider._current_tokens = OAuthToken(access_token="token")
    provider._token_expiry_time = time.time() + 60

    fake_request_token = AsyncMock()
    provider._request_token = fake_request_token  # type: ignore[assignment]

    await provider.ensure_token()

    assert provider._current_tokens is not None
    fake_request_token.assert_not_awaited()


@pytest.mark.anyio
async def test_client_credentials_validate_token_scopes_rejects_extra() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    token = OAuthToken(access_token="token", scope="alpha beta")

    with pytest.raises(Exception, match="unauthorized scopes"):
        await provider._validate_token_scopes(token)


@pytest.mark.anyio
async def test_client_credentials_validate_token_scopes_accepts_server_defined() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope=None)
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    token = OAuthToken(access_token="token", scope="delta")

    await provider._validate_token_scopes(token)


@pytest.mark.anyio
async def test_client_credentials_async_auth_flow_handles_401(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    async def fake_initialize() -> None:
        provider._current_tokens = None

    async def fake_ensure_token() -> None:
        provider._current_tokens = OAuthToken(access_token="flow-token")

    provider.initialize = fake_initialize  # type: ignore[assignment]
    provider.ensure_token = fake_ensure_token  # type: ignore[assignment]

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert prepared_request.headers["Authorization"] == "Bearer flow-token"

    response = httpx.Response(401, request=prepared_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(response)

    assert provider._current_tokens is None


@pytest.mark.anyio
async def test_client_credentials_async_auth_flow_with_cached_token() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    provider._current_tokens = OAuthToken(access_token="cached")
    provider._token_expiry_time = time.time() + 60

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert prepared_request.headers["Authorization"] == "Bearer cached"

    response = httpx.Response(200, request=prepared_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(response)


@pytest.mark.anyio
async def test_client_credentials_async_auth_flow_without_access_token_header(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = ClientCredentialsProvider("https://api.example.com/service", client_metadata, storage)

    async def fake_initialize() -> None:
        provider._current_tokens = None

    async def fake_ensure_token() -> None:
        provider._current_tokens = None

    provider.initialize = fake_initialize  # type: ignore[assignment]
    provider.ensure_token = fake_ensure_token  # type: ignore[assignment]

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert "Authorization" not in prepared_request.headers

    response = httpx.Response(200, request=prepared_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(response)


@pytest.mark.anyio
async def test_token_exchange_request_token(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")

    subject_supplier = AsyncMock(return_value="subject-token")
    actor_supplier = AsyncMock(return_value="actor-token")

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=subject_supplier,
        subject_token_type="access_token",
        actor_token_supplier=actor_supplier,
        actor_token_type="jwt",
        audience="https://audience.example.com",
        resource="https://resource.example.com",
    )

    metadata_response = _make_response(200, json_data=_metadata_json())
    registration_response = _make_response(200, json_data=_registration_json())
    token_response = _make_response(200, json_data=_token_json("alpha"))

    clients = [
        DummyAsyncClient(send_responses=[metadata_response]),
        DummyAsyncClient(send_responses=[registration_response]),
        DummyAsyncClient(post_responses=[token_response]),
    ]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    await provider._request_token()

    assert storage.tokens is not None
    assert storage.tokens.access_token == "access-token"
    assert provider._current_tokens is storage.tokens
    assert provider._token_expiry_time is not None
    subject_supplier.assert_awaited_once()
    actor_supplier.assert_awaited_once()


@pytest.mark.anyio
async def test_token_exchange_request_token_handles_invalid_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")

    subject_supplier = AsyncMock(return_value="subject-token")
    actor_supplier = AsyncMock(return_value="actor-token")

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=subject_supplier,
        subject_token_type="access_token",
        actor_token_supplier=actor_supplier,
        actor_token_type="jwt",
        audience="https://audience.example.com",
    )

    metadata_responses = [
        _make_response(200, json_data={"issuer": "https://auth.example.com"}),
        _make_response(302),
    ]
    registration_response = _make_response(200, json_data=_registration_json())
    token_response = _make_response(
        200,
        json_data={
            "access_token": "exchange-token",
            "token_type": "Bearer",
            "scope": "alpha",
        },
    )

    clients = [
        DummyAsyncClient(send_responses=metadata_responses),
        DummyAsyncClient(send_responses=[registration_response]),
        DummyAsyncClient(post_responses=[token_response]),
    ]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    await provider._request_token()

    assert storage.tokens is not None
    assert storage.tokens.access_token == "exchange-token"
    assert provider._token_expiry_time is None
    subject_supplier.assert_awaited_once()
    actor_supplier.assert_awaited_once()


@pytest.mark.anyio
async def test_token_exchange_request_token_excludes_resource_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    subject_supplier = AsyncMock(return_value="subject-token")

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=subject_supplier,
    )

    provider._metadata = OAuthMetadata.model_validate(_metadata_json())
    provider._client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")
    provider.resource = None

    class RecordingAsyncClient(DummyAsyncClient):
        def __init__(self) -> None:
            super().__init__(post_responses=[_make_response(200, json_data=_token_json())])
            self.last_data: dict[str, str] | None = None

        async def post(self, url: str, *, data: dict[str, str], headers: dict[str, str]) -> httpx.Response:
            self.last_data = data
            return await super().post(url, data=data, headers=headers)

    clients: list[DummyAsyncClient] = [RecordingAsyncClient()]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    await provider._request_token()

    recorded_client = cast(RecordingAsyncClient, clients[0])
    assert recorded_client.last_data is not None
    assert "resource" not in recorded_client.last_data


@pytest.mark.anyio
async def test_token_exchange_request_token_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    provider._metadata = OAuthMetadata.model_validate(_metadata_json())
    provider._client_info = OAuthClientInformationFull(client_id="client", client_secret="secret")

    clients = [DummyAsyncClient(post_responses=[_make_response(400)])]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    with pytest.raises(Exception, match="Token request failed"):
        await provider._request_token()


def test_token_exchange_has_valid_token_checks_expiry() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    provider._current_tokens = OAuthToken(access_token="token")
    provider._token_expiry_time = time.time() - 1

    assert not provider._has_valid_token()


@pytest.mark.anyio
async def test_token_exchange_validate_token_scopes_returns_when_missing() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    token = OAuthToken(access_token="token", scope=None)

    await provider._validate_token_scopes(token)


@pytest.mark.anyio
async def test_token_exchange_get_or_register_client(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    registration_response = _make_response(200, json_data=_registration_json())
    clients = [DummyAsyncClient(send_responses=[registration_response])]
    monkeypatch.setattr("mcp.client.auth.oauth2.httpx.AsyncClient", AsyncClientFactory(clients))

    client_info = await provider._get_or_register_client()

    assert client_info.client_id == "client-id"
    assert storage.client_info is client_info


@pytest.mark.anyio
async def test_token_exchange_initialize_loads_cached_values() -> None:
    storage = InMemoryStorage()
    stored_token = OAuthToken(access_token="cached-token")
    stored_client = OAuthClientInformationFull(client_id="cached-client")
    storage.tokens = stored_token
    storage.client_info = stored_client

    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    await provider.initialize()

    assert provider._current_tokens is stored_token
    assert provider._client_info is stored_client


@pytest.mark.anyio
async def test_token_exchange_validate_token_scopes_rejects_extra() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope="alpha")

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    token = OAuthToken(access_token="token", scope="alpha beta")

    with pytest.raises(Exception, match="unauthorized scopes"):
        await provider._validate_token_scopes(token)


@pytest.mark.anyio
async def test_token_exchange_validate_token_scopes_accepts_server_defined() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris(), scope=None)

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    token = OAuthToken(access_token="token", scope="delta")

    await provider._validate_token_scopes(token)


@pytest.mark.anyio
async def test_token_exchange_async_auth_flow_handles_401(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    async def fake_initialize() -> None:
        provider._current_tokens = None

    async def fake_ensure_token() -> None:
        provider._current_tokens = OAuthToken(access_token="flow-token")

    provider.initialize = fake_initialize  # type: ignore[assignment]
    provider.ensure_token = fake_ensure_token  # type: ignore[assignment]

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert prepared_request.headers["Authorization"] == "Bearer flow-token"

    response = httpx.Response(401, request=prepared_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(response)

    assert provider._current_tokens is None


@pytest.mark.anyio
async def test_token_exchange_async_auth_flow_with_cached_token() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    provider._current_tokens = OAuthToken(access_token="cached")
    provider._token_expiry_time = time.time() + 60

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert prepared_request.headers["Authorization"] == "Bearer cached"

    response = httpx.Response(200, request=prepared_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(response)


@pytest.mark.anyio
async def test_token_exchange_async_auth_flow_without_access_token_header(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    async def fake_initialize() -> None:
        provider._current_tokens = None

    async def fake_ensure_token() -> None:
        provider._current_tokens = None

    provider.initialize = fake_initialize  # type: ignore[assignment]
    provider.ensure_token = fake_ensure_token  # type: ignore[assignment]

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert "Authorization" not in prepared_request.headers

    response = httpx.Response(200, request=prepared_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(response)


@pytest.mark.anyio
async def test_token_exchange_get_or_register_client_skips_request_when_not_needed() -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    def fake_create_registration_request(
        self: TokenExchangeProvider, metadata: OAuthMetadata | None
    ) -> httpx.Request | None:
        self._client_info = OAuthClientInformationFull(client_id="existing-client")
        return None

    provider._metadata = OAuthMetadata.model_validate(_metadata_json())
    provider._create_registration_request = MethodType(fake_create_registration_request, provider)

    client_info = await provider._get_or_register_client()

    assert client_info.client_id == "existing-client"


@pytest.mark.anyio
async def test_token_exchange_ensure_token_returns_when_valid() -> None:
    storage = InMemoryStorage()
    client_metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())

    provider = TokenExchangeProvider(
        "https://api.example.com/service",
        client_metadata,
        storage,
        subject_token_supplier=AsyncMock(return_value="subject-token"),
    )

    provider._current_tokens = OAuthToken(access_token="token")
    provider._token_expiry_time = time.time() + 60

    fake_request_token = AsyncMock()
    provider._request_token = fake_request_token  # type: ignore[assignment]

    await provider.ensure_token()

    assert provider._current_tokens is not None
    fake_request_token.assert_not_awaited()


@pytest.mark.anyio
async def test_oauth_client_provider_performs_full_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = OAuthClientProvider("https://api.example.com/service", metadata, storage)
    provider._initialized = True

    def fake_build_resource_urls(self: OAuthClientProvider, response: httpx.Response) -> list[str]:
        return ["https://resource.example.com/.well-known"]

    async def fake_handle_resource(self: OAuthClientProvider, response: httpx.Response) -> bool:
        self.context.auth_server_url = "https://auth.example.com"
        return True

    def fake_get_discovery_urls(self: OAuthClientProvider, url: str) -> list[str]:
        assert url == "https://auth.example.com"
        return ["https://auth.example.com/.well-known/oauth"]

    def fake_create_oauth_metadata_request(self: OAuthClientProvider, url: str) -> httpx.Request:
        return httpx.Request("GET", url)

    async def fake_handle_oauth_metadata(self: OAuthClientProvider, response: httpx.Response) -> None:
        self._metadata = OAuthMetadata.model_validate(_metadata_json())

    def fake_create_registration_request(
        self: OAuthClientProvider, metadata: OAuthMetadata | None
    ) -> httpx.Request | None:
        return httpx.Request("POST", "https://auth.example.com/register")

    async def fake_handle_registration(self: OAuthClientProvider, response: httpx.Response) -> None:
        client = OAuthClientInformationFull(client_id="client", client_secret="secret")
        self.context.client_info = client
        self._client_info = client

    async def fake_perform_authorization(self: OAuthClientProvider) -> httpx.Request:
        return httpx.Request("POST", "https://auth.example.com/token")

    async def fake_handle_token(self: OAuthClientProvider, response: httpx.Response) -> None:
        token = OAuthToken(access_token="flow-token", scope="alpha beta")
        self.context.current_tokens = token
        await self.context.storage.set_tokens(token)

    monkeypatch.setattr(
        provider,
        "_build_protected_resource_discovery_urls",
        MethodType(fake_build_resource_urls, provider),
    )
    monkeypatch.setattr(provider, "_handle_protected_resource_response", MethodType(fake_handle_resource, provider))
    monkeypatch.setattr(provider, "_get_discovery_urls", MethodType(fake_get_discovery_urls, provider))
    monkeypatch.setattr(
        provider,
        "_create_oauth_metadata_request",
        MethodType(fake_create_oauth_metadata_request, provider),
    )
    monkeypatch.setattr(provider, "_handle_oauth_metadata_response", MethodType(fake_handle_oauth_metadata, provider))
    monkeypatch.setattr(
        provider,
        "_create_registration_request",
        MethodType(fake_create_registration_request, provider),
    )
    monkeypatch.setattr(
        provider,
        "_handle_registration_response",
        MethodType(fake_handle_registration, provider),
    )
    monkeypatch.setattr(provider, "_perform_authorization", MethodType(fake_perform_authorization, provider))
    monkeypatch.setattr(provider, "_handle_token_response", MethodType(fake_handle_token, provider))

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert "Authorization" not in prepared_request.headers

    headers = {"WWW-Authenticate": 'Bearer scope="alpha beta" resource_metadata="https://resource.example.com"'}
    first_response = httpx.Response(401, headers=headers, request=prepared_request)

    discovery_request = await flow.asend(first_response)
    discovery_response = httpx.Response(200, request=discovery_request)

    metadata_request = await flow.asend(discovery_response)
    metadata_response = httpx.Response(200, request=metadata_request)

    registration_request = await flow.asend(metadata_response)
    registration_response = httpx.Response(200, request=registration_request)

    token_request = await flow.asend(registration_response)
    token_response = httpx.Response(200, request=token_request)

    retry_request = await flow.asend(token_response)
    assert retry_request.headers["Authorization"] == "Bearer flow-token"

    final_response = httpx.Response(200, request=retry_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(final_response)


@pytest.mark.anyio
async def test_oauth_client_provider_metadata_discovery_skips_when_no_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = InMemoryStorage()
    metadata = OAuthClientMetadata(redirect_uris=_redirect_uris())
    provider = OAuthClientProvider("https://api.example.com/service", metadata, storage)
    provider._initialized = True

    client = OAuthClientInformationFull(client_id="client", client_secret="secret")
    provider._metadata = OAuthMetadata.model_validate(_metadata_json())
    provider._client_info = client
    provider.context.client_info = client

    def fake_build_resource_urls(self: OAuthClientProvider, response: httpx.Response) -> list[str]:
        return ["https://resource.example.com/.well-known"]

    async def fake_handle_resource(self: OAuthClientProvider, response: httpx.Response) -> bool:
        self.context.auth_server_url = "https://auth.example.com"
        return True

    def fake_get_discovery_urls(self: OAuthClientProvider, url: str) -> list[str]:
        assert url == "https://auth.example.com"
        return []

    async def fake_perform_authorization(self: OAuthClientProvider) -> httpx.Request:
        return httpx.Request("POST", "https://auth.example.com/token")

    async def fake_handle_token(self: OAuthClientProvider, response: httpx.Response) -> None:
        token = OAuthToken(access_token="flow-token", scope="alpha")
        self.context.current_tokens = token
        await self.context.storage.set_tokens(token)

    def fake_select_scopes(self: OAuthClientProvider, response: httpx.Response) -> None:
        return None

    provider._select_scopes = MethodType(fake_select_scopes, provider)
    monkeypatch.setattr(
        provider, "_build_protected_resource_discovery_urls", MethodType(fake_build_resource_urls, provider)
    )
    monkeypatch.setattr(provider, "_handle_protected_resource_response", MethodType(fake_handle_resource, provider))
    monkeypatch.setattr(provider, "_get_discovery_urls", MethodType(fake_get_discovery_urls, provider))
    monkeypatch.setattr(provider, "_perform_authorization", MethodType(fake_perform_authorization, provider))
    monkeypatch.setattr(provider, "_handle_token_response", MethodType(fake_handle_token, provider))

    request = httpx.Request("GET", "https://api.example.com/resource")
    flow = provider.async_auth_flow(request)

    prepared_request = await anext(flow)
    assert "Authorization" not in prepared_request.headers

    headers = {"WWW-Authenticate": 'Bearer resource_metadata="https://resource.example.com/.well-known"'}
    first_response = httpx.Response(401, headers=headers, request=prepared_request)

    discovery_request = await flow.asend(first_response)
    discovery_response = httpx.Response(200, request=discovery_request)

    token_request = await flow.asend(discovery_response)
    assert isinstance(token_request, httpx.Request)

    token_response = httpx.Response(200, request=token_request)
    retry_request = await flow.asend(token_response)
    assert retry_request.headers["Authorization"] == "Bearer flow-token"

    final_response = httpx.Response(200, request=retry_request)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(final_response)
