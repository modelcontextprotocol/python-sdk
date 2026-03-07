"""Tests for AuthlibOAuthAdapter and AuthlibAdapterConfig.

Follows codebase conventions:
- Function-based tests (no Test-prefixed classes)
- @pytest.mark.anyio for all async tests
- Mocks via unittest.mock; never a fixed sleep for async waits
- 100% branch coverage target
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mcp.client.auth import AuthlibAdapterConfig, AuthlibOAuthAdapter
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.shared.auth import OAuthToken

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _InMemoryStorage:
    """Minimal in-memory TokenStorage for tests."""

    def __init__(self, initial: OAuthToken | None = None) -> None:
        self._token = initial
        self._client_info = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._token

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._token = tokens

    async def get_client_info(self) -> None:
        return self._client_info  # pragma: no cover

    async def set_client_info(self, client_info: Any) -> None:  # pragma: no cover
        self._client_info = client_info


def _make_config(**kwargs: Any) -> AuthlibAdapterConfig:
    defaults: dict[str, Any] = {
        "token_endpoint": "https://auth.example.com/token",
        "client_id": "test-client",
        "client_secret": "test-secret",
    }
    defaults.update(kwargs)
    return AuthlibAdapterConfig(**defaults)


def _make_adapter(config: AuthlibAdapterConfig | None = None, **kwargs: Any) -> AuthlibOAuthAdapter:
    return AuthlibOAuthAdapter(
        config=config or _make_config(),
        storage=_InMemoryStorage(),
        **kwargs,
    )


def _mock_response(status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("GET", "https://api.example.com/"))


# ---------------------------------------------------------------------------
# AuthlibAdapterConfig tests
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    """Default values are applied correctly."""
    cfg = AuthlibAdapterConfig(token_endpoint="https://t.example.com/token", client_id="cid")
    assert cfg.client_secret is None
    assert cfg.scopes is None
    assert cfg.token_endpoint_auth_method == "client_secret_basic"
    assert cfg.authorization_endpoint is None
    assert cfg.redirect_uri is None
    assert cfg.leeway == 60
    assert cfg.extra_token_params is None


def test_config_all_fields() -> None:
    """All fields are stored correctly when provided."""
    cfg = AuthlibAdapterConfig(
        token_endpoint="https://t.example.com/token",
        client_id="cid",
        client_secret="s3cr3t",
        scopes=["read", "write"],
        token_endpoint_auth_method="client_secret_post",
        authorization_endpoint="https://t.example.com/authorize",
        redirect_uri="https://app.example.com/callback",
        leeway=30,
        extra_token_params={"audience": "https://api.example.com"},
    )
    assert cfg.client_secret == "s3cr3t"
    assert cfg.scopes == ["read", "write"]
    assert cfg.token_endpoint_auth_method == "client_secret_post"
    assert cfg.authorization_endpoint == "https://t.example.com/authorize"
    assert cfg.redirect_uri == "https://app.example.com/callback"
    assert cfg.leeway == 30
    assert cfg.extra_token_params == {"audience": "https://api.example.com"}


# ---------------------------------------------------------------------------
# AuthlibOAuthAdapter construction
# ---------------------------------------------------------------------------


def test_adapter_construction_scope_joined() -> None:
    """Scopes list is joined as a space-separated string for Authlib."""
    cfg = _make_config(scopes=["read", "write", "admin"])
    adapter = AuthlibOAuthAdapter(config=cfg, storage=_InMemoryStorage())
    assert adapter._client.scope == "read write admin"


def test_adapter_construction_no_scope() -> None:
    """No scope param produces None scope on the Authlib client."""
    adapter = _make_adapter()
    assert adapter._client.scope is None


def test_adapter_exported_from_package() -> None:
    """AuthlibOAuthAdapter and AuthlibAdapterConfig are importable from the package root."""
    from mcp.client.auth import AuthlibAdapterConfig as Cfg
    from mcp.client.auth import AuthlibOAuthAdapter as Adp

    assert Adp is AuthlibOAuthAdapter
    assert Cfg is AuthlibAdapterConfig


# ---------------------------------------------------------------------------
# _initialize
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_initialize_loads_stored_token() -> None:
    """Stored OAuthToken is converted to an Authlib token dict on init."""
    stored = OAuthToken(
        access_token="at-123",
        token_type="Bearer",
        expires_in=3600,
        scope="read",
        refresh_token="rt-456",
    )
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=_InMemoryStorage(stored))
    await adapter._initialize()

    tok = adapter._client.token
    assert tok is not None
    assert tok["access_token"] == "at-123"
    assert tok["token_type"] == "Bearer"
    assert tok["expires_in"] == 3600
    assert tok["scope"] == "read"
    assert tok["refresh_token"] == "rt-456"
    assert adapter._initialized is True


@pytest.mark.anyio
async def test_initialize_no_stored_token() -> None:
    """With no persisted token, Authlib client token stays None."""
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=_InMemoryStorage(None))
    await adapter._initialize()

    assert adapter._client.token is None
    assert adapter._initialized is True


@pytest.mark.anyio
async def test_initialize_token_without_optional_fields() -> None:
    """Token with no refresh_token, scope, or expires_in loads correctly."""
    stored = OAuthToken(access_token="at-only", token_type="Bearer")
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=_InMemoryStorage(stored))
    await adapter._initialize()

    tok = adapter._client.token
    assert tok is not None
    assert tok["access_token"] == "at-only"
    assert "refresh_token" not in tok
    assert "scope" not in tok
    assert "expires_in" not in tok


# ---------------------------------------------------------------------------
# _on_token_update (storage callback)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_on_token_update_persists_full_token() -> None:
    """_on_token_update stores all fields via TokenStorage.set_tokens."""
    storage = _InMemoryStorage()
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=storage)

    await adapter._on_token_update(
        {
            "access_token": "new-at",
            "token_type": "bearer",
            "expires_in": 1800,
            "scope": "read write",
            "refresh_token": "new-rt",
        }
    )

    saved = await storage.get_tokens()
    assert saved is not None
    assert saved.access_token == "new-at"
    assert saved.token_type == "Bearer"  # normalized
    assert saved.expires_in == 1800
    assert saved.scope == "read write"
    assert saved.refresh_token == "new-rt"


@pytest.mark.anyio
async def test_on_token_update_missing_optional_fields() -> None:
    """_on_token_update handles token dict without refresh_token / expires_in."""
    storage = _InMemoryStorage()
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=storage)

    await adapter._on_token_update({"access_token": "bare-at"})

    saved = await storage.get_tokens()
    assert saved is not None
    assert saved.access_token == "bare-at"
    assert saved.refresh_token is None
    assert saved.expires_in is None


# ---------------------------------------------------------------------------
# _fetch_client_credentials_token
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_client_credentials_calls_fetch_token() -> None:
    """_fetch_client_credentials_token calls Authlib fetch_token with correct params."""
    adapter = _make_adapter()
    adapter._initialized = True

    fake_token: dict[str, Any] = {"access_token": "cc-token", "token_type": "Bearer"}

    with patch.object(adapter._client, "fetch_token", new=AsyncMock(return_value=fake_token)):
        adapter._client.token = fake_token  # simulate Authlib setting it
        with patch.object(adapter, "_on_token_update", new=AsyncMock()) as mock_update:
            await adapter._fetch_client_credentials_token()

    mock_update.assert_awaited_once()


@pytest.mark.anyio
async def test_fetch_client_credentials_with_extra_params() -> None:
    """extra_token_params are forwarded to fetch_token."""
    cfg = _make_config(extra_token_params={"audience": "https://api.example.com"})
    adapter = AuthlibOAuthAdapter(config=cfg, storage=_InMemoryStorage())
    adapter._initialized = True
    adapter._client.token = None

    with patch.object(adapter._client, "fetch_token", new=AsyncMock()) as mock_ft:
        await adapter._fetch_client_credentials_token()

    mock_ft.assert_awaited_once()
    _, kwargs = mock_ft.call_args
    assert kwargs.get("audience") == "https://api.example.com"
    assert kwargs.get("grant_type") == "client_credentials"


@pytest.mark.anyio
async def test_fetch_client_credentials_no_extra_params() -> None:
    """Without extra_token_params only grant_type is passed."""
    adapter = _make_adapter()
    adapter._client.token = None

    with patch.object(adapter._client, "fetch_token", new=AsyncMock()) as mock_ft:
        await adapter._fetch_client_credentials_token()

    _, kwargs = mock_ft.call_args
    assert kwargs.get("grant_type") == "client_credentials"
    assert "audience" not in kwargs


# ---------------------------------------------------------------------------
# _perform_authorization_code_flow — validation branches
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth_code_flow_missing_authorization_endpoint_raises() -> None:
    """OAuthFlowError when authorization_endpoint is not set."""
    adapter = _make_adapter()
    with pytest.raises(OAuthFlowError, match="authorization_endpoint"):
        await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_missing_redirect_uri_raises() -> None:
    """OAuthFlowError when redirect_uri is not set."""
    cfg = _make_config(authorization_endpoint="https://auth.example.com/authorize")
    adapter = AuthlibOAuthAdapter(config=cfg, storage=_InMemoryStorage())
    with pytest.raises(OAuthFlowError, match="redirect_uri"):
        await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_missing_redirect_handler_raises() -> None:
    """OAuthFlowError when redirect_handler is None."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    adapter = AuthlibOAuthAdapter(config=cfg, storage=_InMemoryStorage())
    with pytest.raises(OAuthFlowError, match="redirect_handler"):
        await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_missing_callback_handler_raises() -> None:
    """OAuthFlowError when callback_handler is None."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=_InMemoryStorage(),
        redirect_handler=AsyncMock(),
        callback_handler=None,
    )
    with pytest.raises(OAuthFlowError, match="callback_handler"):
        await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_state_mismatch_raises() -> None:
    """OAuthFlowError when state returned by callback doesn't match."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    redirect_calls: list[str] = []

    async def redirect(url: str) -> None:
        redirect_calls.append(url)

    async def callback() -> tuple[str, str | None]:
        return "some-code", "WRONG-STATE"

    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=_InMemoryStorage(),
        redirect_handler=redirect,
        callback_handler=callback,
    )

    with patch.object(
        adapter._client,
        "create_authorization_url",
        return_value=("https://auth.example.com/authorize?code_challenge=x", "correct-state"),
    ):
        with pytest.raises(OAuthFlowError, match="State mismatch"):
            await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_none_state_raises() -> None:
    """OAuthFlowError when callback returns None as state (covers the is-None branch of the or-guard)."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )

    async def redirect(_url: str) -> None:
        pass

    async def callback() -> tuple[str, str | None]:
        return "some-code", None  # state is None → first branch of the `or` fires

    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=_InMemoryStorage(),
        redirect_handler=redirect,
        callback_handler=callback,
    )

    with pytest.raises(OAuthFlowError, match="State mismatch"):
        await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_no_token_after_fetch() -> None:
    """When fetch_token leaves client.token as None, _on_token_update is NOT called."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    captured_state: list[str] = []

    async def redirect(url: str) -> None:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        captured_state.extend(qs.get("state", []))

    async def callback() -> tuple[str, str | None]:
        return "auth-code-xyz", captured_state[0] if captured_state else None

    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=_InMemoryStorage(),
        redirect_handler=redirect,
        callback_handler=callback,
    )
    adapter._client.token = None  # ensure no pre-existing token

    with (
        patch.object(adapter._client, "fetch_token", new=AsyncMock()),  # fetch_token does NOT set token
        patch.object(adapter, "_on_token_update", new=AsyncMock()) as mock_update,
    ):
        # Token remains None after fetch_token; _on_token_update must NOT be called
        await adapter._perform_authorization_code_flow()

    mock_update.assert_not_awaited()


@pytest.mark.anyio
async def test_auth_code_flow_empty_code_raises() -> None:
    """OAuthFlowError when callback returns empty authorization code."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    captured_state: list[str] = []

    async def redirect(url: str) -> None:
        # URL contains state= so we can extract it
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        captured_state.extend(qs.get("state", []))

    async def callback() -> tuple[str, str | None]:
        return "", captured_state[0] if captured_state else None

    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=_InMemoryStorage(),
        redirect_handler=redirect,
        callback_handler=callback,
    )

    with pytest.raises(OAuthFlowError, match="No authorization code"):
        await adapter._perform_authorization_code_flow()


@pytest.mark.anyio
async def test_auth_code_flow_success() -> None:
    """Happy path: redirect called, callback returns code+state, fetch_token invoked."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    captured_state: list[str] = []

    async def redirect(url: str) -> None:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        captured_state.extend(qs.get("state", []))

    async def callback() -> tuple[str, str | None]:
        return "auth-code-xyz", captured_state[0] if captured_state else None

    storage = _InMemoryStorage()
    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=storage,
        redirect_handler=redirect,
        callback_handler=callback,
    )

    fake_token: dict[str, Any] = {"access_token": "code-at", "token_type": "Bearer"}
    with patch.object(adapter._client, "fetch_token", new=AsyncMock()) as mock_ft:
        adapter._client.token = fake_token
        await adapter._perform_authorization_code_flow()

    mock_ft.assert_awaited_once()
    _, kwargs = mock_ft.call_args
    assert kwargs["grant_type"] == "authorization_code"
    assert kwargs["code"] == "auth-code-xyz"
    assert kwargs["redirect_uri"] == "https://app.example.com/cb"
    assert "code_verifier" in kwargs

    saved = await storage.get_tokens()
    assert saved is not None
    assert saved.access_token == "code-at"


# ---------------------------------------------------------------------------
# async_auth_flow
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth_flow_injects_bearer_when_token_valid() -> None:
    """On first use with a valid stored token, Bearer header is injected."""
    stored = OAuthToken(access_token="valid-at", token_type="Bearer")
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=_InMemoryStorage(stored))

    request = httpx.Request("GET", "https://api.example.com/resource")
    ok_response = _mock_response(200)

    with patch.object(adapter._client, "ensure_active_token", new=AsyncMock()):
        flow = adapter.async_auth_flow(request)
        sent = await flow.__anext__()
        assert sent.headers.get("Authorization") == "Bearer valid-at"
        with pytest.raises(StopAsyncIteration):
            await flow.asend(ok_response)


@pytest.mark.anyio
async def test_auth_flow_no_bearer_when_no_token() -> None:
    """When storage is empty and no 401, no Authorization header is added."""
    adapter = _make_adapter()

    request = httpx.Request("GET", "https://api.example.com/resource")
    ok_response = _mock_response(200)

    with patch.object(adapter._client, "ensure_active_token", new=AsyncMock()):
        flow = adapter.async_auth_flow(request)
        sent = await flow.__anext__()
        assert "Authorization" not in sent.headers
        with pytest.raises(StopAsyncIteration):
            await flow.asend(ok_response)


@pytest.mark.anyio
async def test_auth_flow_client_credentials_on_401() -> None:
    """On 401, client_credentials token is acquired and request is retried."""
    adapter = _make_adapter()  # no authorization_endpoint → client_credentials

    request = httpx.Request("GET", "https://api.example.com/resource")
    response_401 = _mock_response(401)
    response_200 = _mock_response(200)

    new_token: dict[str, Any] = {"access_token": "fresh-at", "token_type": "Bearer"}

    async def fake_fetch(url: str, **kwargs: Any) -> dict[str, Any]:
        adapter._client.token = new_token
        return new_token

    with (
        patch.object(adapter._client, "ensure_active_token", new=AsyncMock()),
        patch.object(adapter._client, "fetch_token", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(adapter, "_on_token_update", new=AsyncMock()),
    ):
        flow = adapter.async_auth_flow(request)
        first_request = await flow.__anext__()
        assert "Authorization" not in first_request.headers

        second_request = await flow.asend(response_401)
        assert second_request.headers.get("Authorization") == "Bearer fresh-at"

        with pytest.raises(StopAsyncIteration):
            await flow.asend(response_200)


@pytest.mark.anyio
async def test_auth_flow_authorization_code_on_401() -> None:
    """On 401, authorization_code flow is triggered when endpoint is configured."""
    cfg = _make_config(
        authorization_endpoint="https://auth.example.com/authorize",
        redirect_uri="https://app.example.com/cb",
    )
    captured_state: list[str] = []

    async def redirect(url: str) -> None:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        captured_state.extend(qs.get("state", []))

    async def callback() -> tuple[str, str | None]:
        return "auth-code", captured_state[0] if captured_state else None

    storage = _InMemoryStorage()
    adapter = AuthlibOAuthAdapter(
        config=cfg,
        storage=storage,
        redirect_handler=redirect,
        callback_handler=callback,
    )

    request = httpx.Request("GET", "https://api.example.com/resource")
    response_401 = _mock_response(401)
    response_200 = _mock_response(200)

    new_token: dict[str, Any] = {"access_token": "ac-token", "token_type": "Bearer"}

    async def fake_fetch(url: str, **kwargs: Any) -> dict[str, Any]:
        adapter._client.token = new_token
        return new_token

    with (
        patch.object(adapter._client, "ensure_active_token", new=AsyncMock()),
        patch.object(adapter._client, "fetch_token", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(adapter, "_on_token_update", new=AsyncMock()),
    ):
        flow = adapter.async_auth_flow(request)
        await flow.__anext__()  # initial request
        second_request = await flow.asend(response_401)  # triggers auth_code flow
        assert second_request.headers.get("Authorization") == "Bearer ac-token"

        with pytest.raises(StopAsyncIteration):
            await flow.asend(response_200)


@pytest.mark.anyio
async def test_auth_flow_ensure_active_token_skipped_when_no_token() -> None:
    """ensure_active_token is NOT called when the client has no token yet."""
    adapter = _make_adapter()
    adapter._initialized = True
    adapter._client.token = None

    request = httpx.Request("GET", "https://api.example.com/resource")
    ok_response = _mock_response(200)

    with patch.object(adapter._client, "ensure_active_token", new=AsyncMock()) as mock_eat:
        flow = adapter.async_auth_flow(request)
        await flow.__anext__()
        mock_eat.assert_not_awaited()
        with pytest.raises(StopAsyncIteration):
            await flow.asend(ok_response)


@pytest.mark.anyio
async def test_auth_flow_ensure_active_token_called_when_token_present() -> None:
    """ensure_active_token IS called when a token already exists."""
    stored = OAuthToken(access_token="existing-at", token_type="Bearer")
    adapter = AuthlibOAuthAdapter(config=_make_config(), storage=_InMemoryStorage(stored))

    request = httpx.Request("GET", "https://api.example.com/resource")
    ok_response = _mock_response(200)

    with patch.object(adapter._client, "ensure_active_token", new=AsyncMock()) as mock_eat:
        flow = adapter.async_auth_flow(request)
        await flow.__anext__()
        mock_eat.assert_awaited_once()
        with pytest.raises(StopAsyncIteration):
            await flow.asend(ok_response)


# ---------------------------------------------------------------------------
# _inject_bearer edge cases
# ---------------------------------------------------------------------------


def test_inject_bearer_adds_header() -> None:
    """_inject_bearer adds Authorization header when token is set."""
    adapter = _make_adapter()
    adapter._client.token = {"access_token": "tok", "token_type": "Bearer"}
    request = httpx.Request("GET", "https://api.example.com/")
    adapter._inject_bearer(request)
    assert request.headers["Authorization"] == "Bearer tok"


def test_inject_bearer_skips_when_no_access_token() -> None:
    """_inject_bearer does not add header when access_token is missing."""
    adapter = _make_adapter()
    adapter._client.token = {}  # empty dict — no access_token key
    request = httpx.Request("GET", "https://api.example.com/")
    adapter._inject_bearer(request)
    assert "Authorization" not in request.headers


def test_inject_bearer_skips_when_token_is_none() -> None:
    """_inject_bearer does not add header when Authlib token is None."""
    adapter = _make_adapter()
    adapter._client.token = None
    request = httpx.Request("GET", "https://api.example.com/")
    adapter._inject_bearer(request)
    assert "Authorization" not in request.headers
