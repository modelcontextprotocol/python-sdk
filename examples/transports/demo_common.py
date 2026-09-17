"""Shared live-broker checks for the reference adapters."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any, TypeAlias
from uuid import uuid4

import anyio
from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.transport import MessageMetadata, Transport, TransportContext
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool

TransportFactory: TypeAlias = Callable[[AsyncExitStack, str, str, bool], Awaitable[Transport]]


@dataclass(kw_only=True, frozen=True)
class BrokerContext(TransportContext):
    principal: str


def peer_context(metadata: MessageMetadata, *, principal: str, kind: str) -> BrokerContext:
    return BrokerContext(kind=kind, can_send_request=True, principal=principal)


async def verify(factory: TransportFactory, *, kind: str, highlevel: bool, mode: str) -> None:
    """Check real concurrent calls, peer metadata, both server APIs, and shared lifespan."""
    entered = {"alice": anyio.Event(), "bob": anyio.Event()}
    lifecycle: list[str] = []

    async def identity(transport: TransportContext | None) -> str:
        assert isinstance(transport, BrokerContext)
        principal = transport.principal
        entered[principal].set()
        await entered["bob" if principal == "alice" else "alice"].wait()
        return principal

    @asynccontextmanager
    async def lifespan(server: Server[Any] | MCPServer[Any]) -> AsyncIterator[None]:
        lifecycle.append("start")
        try:
            yield None
        finally:
            lifecycle.append("stop")

    if highlevel:
        server = MCPServer("Broker", lifespan=lifespan)

        @server.tool()
        async def identify(ctx: Context) -> str:
            return await identity(ctx.transport)

    else:

        async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
            return ListToolsResult(tools=[Tool(name="identify", input_schema={"type": "object"})])

        async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
            assert params.name == "identify"
            return CallToolResult(content=[TextContent(text=await identity(ctx.transport))])

        server = Server("Broker", lifespan=lifespan, on_list_tools=list_tools, on_call_tool=call_tool)

    results: dict[str, str] = {}

    async def call(client: Client, principal: str) -> None:
        result = await client.call_tool("identify")
        content = result.content[0]
        assert isinstance(content, TextContent)
        results[principal] = content.text

    async with AsyncExitStack() as stack:
        sessions = {principal: uuid4().hex for principal in entered}
        transports = {
            principal: await factory(stack, principal, session, True) for principal, session in sessions.items()
        }
        runtime = await stack.enter_async_context(server.serve())
        clients: dict[str, Client] = {}
        for principal, transport in transports.items():
            await runtime.connect(transport, transport_builder=partial(peer_context, principal=principal, kind=kind))
            client_transport = await factory(stack, principal, sessions[principal], False)
            clients[principal] = await stack.enter_async_context(
                Client(client_transport, mode=mode, read_timeout_seconds=5)
            )
        async with anyio.create_task_group() as tg:
            for principal, client in clients.items():
                tg.start_soon(call, client, principal)
        assert results == {"alice": "alice", "bob": "bob"}
        assert lifecycle == ["start"]
    assert lifecycle == ["start", "stop"]
