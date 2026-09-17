"""Exercise the native gRPC binding over a real loopback connection."""

from contextlib import AsyncExitStack

import anyio
import grpc.aio
from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool

from mcp_transport_examples.grpc import grpc_client, grpc_server
from mcp_transport_examples.grpc_context import GRPCContext


async def verify(highlevel: bool, mode: str) -> None:
    if highlevel:
        server = MCPServer("Native gRPC")

        @server.tool()
        async def echo(value: str, ctx: Context) -> str:
            assert isinstance(ctx.transport, GRPCContext)
            assert not ctx.transport.can_send_request
            await ctx.report_progress(1, 2, "halfway")
            return value

    else:

        async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
            return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])

        async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
            assert params.name == "echo"
            assert isinstance(ctx.transport, GRPCContext)
            assert params.arguments is not None
            await ctx.session.report_progress(1, 2, "halfway")
            return CallToolResult(content=[TextContent(text=str(params.arguments["value"]))])

        server = Server("Native gRPC", on_list_tools=list_tools, on_call_tool=call_tool)

    updates: list[tuple[float, float | None, str | None]] = []

    async def progress(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))

    async with AsyncExitStack() as stack:
        listener = grpc.aio.server()
        port = listener.add_insecure_port("127.0.0.1:0")
        stack.push_async_callback(listener.stop, 0)
        runtime = await stack.enter_async_context(server.serve())
        await runtime.connect(grpc_server(listener))
        await listener.start()
        channel = await stack.enter_async_context(grpc.aio.insecure_channel(f"127.0.0.1:{port}"))
        client = await stack.enter_async_context(Client(grpc_client(channel), mode=mode))
        value = "MCP without a JSON-RPC envelope"
        result = await client.call_tool("echo", {"value": value}, progress_callback=progress)
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == value
        assert updates == [(1, 2, "halfway")]


async def main() -> None:
    for highlevel in (False, True):
        for mode in ("auto", "2026-07-28"):
            with anyio.fail_after(5):
                await verify(highlevel, mode)


if __name__ == "__main__":
    anyio.run(main)
