from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.runtime import ServerRuntime
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import Dispatcher
from mcp.shared.transport import DispatcherTransport, TransportContext

server = MCPServer("Dispatcher transport")


@server.tool()
async def greet(name: str, ctx: Context) -> str:
    assert ctx.transport is not None
    assert not ctx.transport.can_send_request
    return f"Hello, {name}!"


def direct_client(runtime: ServerRuntime[Any]) -> DispatcherTransport:
    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        client_dispatcher, server_dispatcher = create_direct_dispatcher_pair()

        @asynccontextmanager
        async def server_connection() -> AsyncIterator[Dispatcher[TransportContext]]:
            try:
                yield server_dispatcher
            finally:
                server_dispatcher.close()

        try:
            await runtime.connect(DispatcherTransport(server_connection()))
            yield client_dispatcher
        finally:
            client_dispatcher.close()
            server_dispatcher.close()

    return DispatcherTransport(connection())


async def main() -> None:
    async with server.serve() as runtime:
        async with Client(direct_client(runtime)) as client:
            result = await client.call_tool("greet", {"name": "Alice"})
            assert result.structured_content == {"result": "Hello, Alice!"}


if __name__ == "__main__":
    anyio.run(main)
