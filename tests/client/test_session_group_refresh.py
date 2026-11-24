"""Integration check for token refresh in a group with two independent providers."""

import contextlib
from typing import Never
from urllib.parse import parse_qsl

import anyio
import pytest
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from mcp.client.auth import OAuthClientProvider
from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from tests.client.test_auth import MockTokenStorage
from tests.client.test_session_group import _by_host, _patch_in_process_clients, _server, _streamable_app


async def _provider(host: str) -> OAuthClientProvider:
    storage = MockTokenStorage()
    client = OAuthClientInformationFull(
        client_id=host, redirect_uris=[AnyUrl("http://localhost/callback")], token_endpoint_auth_method="none"
    )
    await storage.set_client_info(client)
    await storage.set_tokens(OAuthToken(access_token=host, token_type="Bearer", refresh_token=f"{host}-refresh"))

    async def unexpected_redirect(url: str) -> None:
        pytest.fail("Existing credentials should suffice")

    async def unexpected_callback() -> Never:
        pytest.fail("Refresh should not start interactive authorization")

    return OAuthClientProvider(
        server_url=f"http://{host}/mcp",
        client_metadata=client,
        storage=storage,
        redirect_handler=unexpected_redirect,
        callback_handler=unexpected_callback,
    )


@pytest.mark.anyio
async def test_refresh_is_scoped_to_one_session(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _server("Library", "library_search"), _server("Web", "web_search")
    library_headers: list[str | None] = []
    web_headers: list[str | None] = []
    library = _streamable_app(first, library_headers, [])
    grants: list[dict[str, str]] = []

    async def library_with_token_endpoint(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["path"] != "/token":
            await library(scope, receive, send)
            return
        request = Request(scope, receive)
        assert request.method == "POST"
        grants.append(dict(parse_qsl((await request.body()).decode())))
        response = JSONResponse({"access_token": "renewed", "token_type": "Bearer", "expires_in": 3600})
        await response(scope, receive, send)

    hosts = _by_host(
        {"library.example": library_with_token_endpoint, "web.example": _streamable_app(second, web_headers, [])}
    )
    _patch_in_process_clients(monkeypatch, hosts, cancel_on_close=True)
    library_provider = await _provider("library.example")
    web_provider = await _provider("web.example")

    with anyio.fail_after(5):
        async with first.session_manager.run(), second.session_manager.run(), contextlib.AsyncExitStack() as stack:
            group = ClientSessionGroup(exit_stack=stack)
            await group.connect_to_server(
                StreamableHttpParameters(url="http://library.example/mcp", auth=library_provider)
            )
            await group.connect_to_server(StreamableHttpParameters(url="http://web.example/mcp", auth=web_provider))
            assert set(library_headers) == {"Bearer library.example"}
            assert set(web_headers) == {"Bearer web.example"}
            library_headers.clear()
            web_headers.clear()
            library_provider.context.token_expiry_time = 1
            assert (await group.call_tool("library_search")).structured_content == {"result": "Library"}
            assert (await group.call_tool("web_search")).structured_content == {"result": "Web"}

    assert len(grants) == 1
    assert grants[0]["grant_type"] == "refresh_token"
    assert grants[0]["refresh_token"] == "library.example-refresh"
    assert grants[0]["client_id"] == "library.example"
    assert set(library_headers) == {"Bearer renewed"}
    assert set(web_headers) == {"Bearer web.example"}
