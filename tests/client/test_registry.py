"""Regression tests for AuthProtocolRegistry."""

import httpx
import pytest

from mcp.client.auth.protocol import AuthContext
from mcp.client.auth.registry import AuthProtocolRegistry
from mcp.shared.auth import AuthCredentials, AuthProtocolMetadata, ProtectedResourceMetadata


class _MockAuthProtocol:
    """Minimal AuthProtocol implementation for registry tests."""

    protocol_id = "mock"
    protocol_version = "1.0"

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        return AuthCredentials(protocol_id="mock")

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        pass

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return True

    async def discover_metadata(
        self,
        metadata_url: str | None = None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


class _MockOAuth2Protocol:
    protocol_id = "oauth2"
    protocol_version = "2.0"

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        raise NotImplementedError

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        pass

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return True

    async def discover_metadata(
        self,
        metadata_url: str | None = None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


class _MockApiKeyProtocol:
    protocol_id = "api_key"
    protocol_version = "1.0"

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        raise NotImplementedError

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        pass

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        return True

    async def discover_metadata(
        self,
        metadata_url: str | None = None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        return None


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset registry state before and after each test."""
    before = dict(AuthProtocolRegistry._protocols)
    yield
    AuthProtocolRegistry._protocols.clear()
    AuthProtocolRegistry._protocols.update(before)


def test_register_and_get_protocol_class():
    AuthProtocolRegistry.register("mock", _MockAuthProtocol)
    assert AuthProtocolRegistry.get_protocol_class("mock") is _MockAuthProtocol
    assert AuthProtocolRegistry.get_protocol_class("nonexistent") is None


def test_list_registered():
    assert AuthProtocolRegistry.list_registered() == []
    AuthProtocolRegistry.register("oauth2", _MockOAuth2Protocol)
    AuthProtocolRegistry.register("api_key", _MockApiKeyProtocol)
    registered = AuthProtocolRegistry.list_registered()
    assert set(registered) == {"oauth2", "api_key"}


def test_select_protocol_returns_none_when_no_support():
    AuthProtocolRegistry.register("oauth2", _MockOAuth2Protocol)
    assert AuthProtocolRegistry.select_protocol(["api_key", "mutual_tls"]) is None


def test_select_protocol_returns_first_supported():
    AuthProtocolRegistry.register("oauth2", _MockOAuth2Protocol)
    AuthProtocolRegistry.register("api_key", _MockApiKeyProtocol)
    assert AuthProtocolRegistry.select_protocol(["api_key", "oauth2"]) == "api_key"
    assert AuthProtocolRegistry.select_protocol(["oauth2", "api_key"]) == "oauth2"


def test_select_protocol_prefers_default_when_supported():
    AuthProtocolRegistry.register("oauth2", _MockOAuth2Protocol)
    AuthProtocolRegistry.register("api_key", _MockApiKeyProtocol)
    result = AuthProtocolRegistry.select_protocol(
        ["api_key", "oauth2"],
        default_protocol="oauth2",
    )
    assert result == "oauth2"


def test_select_protocol_ignores_default_when_not_supported():
    AuthProtocolRegistry.register("api_key", _MockApiKeyProtocol)
    result = AuthProtocolRegistry.select_protocol(
        ["api_key"],
        default_protocol="oauth2",
    )
    assert result == "api_key"


def test_select_protocol_uses_preferences():
    AuthProtocolRegistry.register("oauth2", _MockOAuth2Protocol)
    AuthProtocolRegistry.register("api_key", _MockApiKeyProtocol)
    result = AuthProtocolRegistry.select_protocol(
        ["oauth2", "api_key"],
        preferences={"oauth2": 10, "api_key": 1},
    )
    assert result == "api_key"


def test_select_protocol_preferences_unknown_protocol_gets_high_priority():
    AuthProtocolRegistry.register("oauth2", _MockOAuth2Protocol)
    AuthProtocolRegistry.register("api_key", _MockApiKeyProtocol)
    result = AuthProtocolRegistry.select_protocol(
        ["oauth2", "api_key"],
        preferences={"api_key": 999},
    )
    assert result in ("oauth2", "api_key")
