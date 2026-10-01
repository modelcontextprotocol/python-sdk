from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.runtime import ServerRuntime
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.transport import MessageMetadata, TransportContext, TransportStreams


@dataclass(kw_only=True, frozen=True)
class PeerContext(TransportContext):
    peer: str


server = MCPServer("Custom transport")


@server.tool()
async def identify(ctx: Context) -> str:
    transport = ctx.transport
    assert isinstance(transport, PeerContext)
    return transport.peer


@asynccontextmanager
async def memory_client(runtime: ServerRuntime[Any], peer: str) -> AsyncIterator[TransportStreams]:
    async with create_client_server_memory_streams() as (client_streams, server_streams):

        @asynccontextmanager
        async def server_transport() -> AsyncIterator[TransportStreams]:
            async with server_streams[0], server_streams[1]:
                yield server_streams

        def build_context(metadata: MessageMetadata) -> PeerContext:
            return PeerContext(kind="memory", can_send_request=True, peer=peer)

        await runtime.connect(server_transport(), transport_builder=build_context)
        yield client_streams


async def main() -> None:
    async with server.serve(max_connections=10) as runtime:
        async with Client(memory_client(runtime, "alice")) as alice:
            async with Client(memory_client(runtime, "bob")) as bob:
                alice_result = await alice.call_tool("identify")
                bob_result = await bob.call_tool("identify")
                assert alice_result.structured_content == {"result": "alice"}
                assert bob_result.structured_content == {"result": "bob"}


if __name__ == "__main__":
    anyio.run(main)
