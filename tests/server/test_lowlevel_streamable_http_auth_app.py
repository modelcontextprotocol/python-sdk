from typing import cast
from unittest.mock import Mock

import pytest
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.lowlevel.server import Server


class DummyTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        return None


def route_paths(app: Starlette) -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
    return paths


@pytest.mark.anyio
async def test_dummy_token_verifier_returns_none():
    verifier = DummyTokenVerifier()

    assert await verifier.verify_token("token") is None


def test_route_paths_ignores_non_string_paths():
    app = Starlette()
    routes = cast(list[object], app.router.routes)
    routes.append(Mock(path="/ok"))
    routes.append(object())

    assert route_paths(app) == {"/ok"}


def test_streamable_http_app_adds_auth_routes_without_token_verifier():
    server = Server("test-server")

    app = server.streamable_http_app(
        host="testserver",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl("https://testserver/mcp"),
        ),
        auth_server_provider=Mock(),
    )

    assert {
        "/mcp",
        "/authorize",
        "/token",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp",
    }.issubset(route_paths(app))


def test_streamable_http_app_skips_resource_metadata_route_when_resource_server_url_missing():
    server = Server("test-server")

    app = server.streamable_http_app(
        host="testserver",
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=None,
        ),
        token_verifier=DummyTokenVerifier(),
    )

    paths = route_paths(app)
    middleware_classes = [middleware.cls for middleware in app.user_middleware]

    assert "/mcp" in paths
    assert "/.well-known/oauth-protected-resource/mcp" not in paths
    assert AuthenticationMiddleware in middleware_classes
    assert AuthContextMiddleware in middleware_classes
