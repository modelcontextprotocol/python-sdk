from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp_simple_auth_client import main as client_module
from mcp_simple_auth_client.main import SimpleAuthClient

from mcp.client.auth import OAuthClientProvider

pytestmark = pytest.mark.anyio


async def test_the_oauth_provider_receives_the_complete_connection_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client preserves path prefixes, the transport path, and the query in the resource identifier."""
    resource_url = "https://mcp.example.com/prefix/mcp?tenant=mcp"
    providers: list[OAuthClientProvider] = []
    session_calls: list[tuple[Any, Any]] = []

    class FakeCallbackServer:
        def __init__(self, port: int) -> None:
            assert port == 3030

        def start(self) -> None:
            pass

    @asynccontextmanager
    async def fake_sse_client(**kwargs: Any) -> AsyncIterator[tuple[object, object]]:
        assert kwargs["url"] == resource_url
        assert isinstance(kwargs["auth"], OAuthClientProvider)
        providers.append(kwargs["auth"])
        yield object(), object()

    async def fake_run_session(self: SimpleAuthClient, read_stream: Any, write_stream: Any) -> None:
        session_calls.append((read_stream, write_stream))

    monkeypatch.setattr(client_module, "CallbackServer", FakeCallbackServer)
    monkeypatch.setattr(client_module, "sse_client", fake_sse_client)
    monkeypatch.setattr(SimpleAuthClient, "_run_session", fake_run_session)

    await SimpleAuthClient(resource_url, transport_type="sse").connect()

    assert [provider.context.server_url for provider in providers] == [resource_url]
    assert len(session_calls) == 1
