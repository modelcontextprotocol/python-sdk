from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.client.auth import OAuthClientProvider
from mcp.shared.message import SessionMessage

CLIENT_ROOT = Path(__file__).parents[3] / "examples" / "clients" / "simple-auth-client"


class SimpleAuthClient(Protocol):
    def __init__(
        self,
        server_url: str,
        transport_type: str = "streamable-http",
        client_metadata_url: str | None = None,
    ) -> None: ...

    async def connect(self) -> None: ...


class ClientModule(Protocol):
    SimpleAuthClient: type[SimpleAuthClient]


@pytest.mark.anyio
async def test_oauth_client_preserves_the_complete_connection_url(
    monkeypatch: pytest.MonkeyPatch,
    load_example_module: Callable[[Path, str], ModuleType],
) -> None:
    """The example passes the opaque MCP endpoint unchanged to its OAuth provider."""
    client_module = cast(ClientModule, load_example_module(CLIENT_ROOT, "mcp_simple_auth_client.main"))
    resource_url = "https://mcp.example.com/prefix/mcp?tenant=mcp"
    providers: list[OAuthClientProvider] = []
    sessions = 0

    class FakeCallbackServer:
        def __init__(self, port: int) -> None:
            assert port == 3030

        def start(self) -> None:
            pass

    @asynccontextmanager
    async def fake_sse_client(
        *, url: str, auth: OAuthClientProvider, timeout: float
    ) -> AsyncIterator[
        tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]]
    ]:
        assert url == resource_url
        assert timeout == 60.0
        providers.append(auth)
        read_send, read_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
        write_send, write_receive = anyio.create_memory_object_stream[SessionMessage](1)
        async with read_send, read_receive, write_send, write_receive:
            yield read_receive, write_send

    async def record_session(
        self: SimpleAuthClient,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
    ) -> None:
        nonlocal sessions
        sessions += 1

    monkeypatch.setattr(client_module, "CallbackServer", FakeCallbackServer)
    monkeypatch.setattr(client_module, "sse_client", fake_sse_client)
    monkeypatch.setattr(client_module.SimpleAuthClient, "_run_session", record_session)

    await client_module.SimpleAuthClient(resource_url, transport_type="sse").connect()

    assert sessions == 1
    assert [str(provider.context.server_url) for provider in providers] == [resource_url]
