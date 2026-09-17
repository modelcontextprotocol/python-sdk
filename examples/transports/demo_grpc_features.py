"""Live checks for subscriptions and multi-round-trip results over native gRPC."""

from contextlib import AsyncExitStack

import anyio
import grpc.aio
from mcp import Client
from mcp.client import ClientRequestContext
from mcp.client.subscriptions import ToolsListChanged
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitRequestParams, ElicitResult, InputRequiredResult

from mcp_transport_examples.grpc import grpc_client, grpc_server


async def verify() -> None:
    server = MCPServer("native features")
    entered = {"alice": anyio.Event(), "bob": anyio.Event()}

    @server.tool()
    async def overlap(label: str, ctx: Context) -> str:
        assert ctx.request_context.request_id == 0
        entered[label].set()
        await entered["bob" if label == "alice" else "alice"].wait()
        return label

    @server.tool()
    async def announce(ctx: Context) -> str:
        await ctx.notify_tools_changed()
        return "announced"

    @server.tool()
    async def confirm(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is not None:
            assert ctx.request_state == "awaiting confirmation"
            answer = ctx.input_responses["confirm"]
            assert isinstance(answer, ElicitResult)
            assert answer.action == "accept"
            return "confirmed"
        return InputRequiredResult(
            input_requests={
                "confirm": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Confirm?", requested_schema={"type": "object", "properties": {}}
                    )
                )
            },
            request_state="awaiting confirmation",
        )

    async def elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content={})

    async with AsyncExitStack() as stack:
        listener = grpc.aio.server()
        port = listener.add_insecure_port("127.0.0.1:0")
        stack.push_async_callback(listener.stop, 0)
        runtime = await stack.enter_async_context(server.serve())
        await runtime.connect(grpc_server(listener))
        await listener.start()
        channel = await stack.enter_async_context(grpc.aio.insecure_channel(f"127.0.0.1:{port}"))
        client = await stack.enter_async_context(Client(grpc_client(channel), elicitation_callback=elicit))
        async with client.listen(tools_list_changed=True) as subscription:
            result = await client.call_tool("announce")
            assert result.structured_content == {"result": "announced"}
            event = await anext(subscription)
            assert isinstance(event, ToolsListChanged)
        result = await client.call_tool("confirm")
        assert result.structured_content == {"result": "confirmed"}

        clients: dict[str, Client] = {}
        for label in entered:
            peer_channel = await stack.enter_async_context(grpc.aio.insecure_channel(f"127.0.0.1:{port}"))
            clients[label] = await stack.enter_async_context(Client(grpc_client(peer_channel), mode="2026-07-28"))

        async def call(label: str, client: Client) -> None:
            result = await client.call_tool("overlap", {"label": label})
            assert result.structured_content == {"result": label}

        async with anyio.create_task_group() as tg:
            for label, peer in clients.items():
                tg.start_soon(call, label, peer)


async def main() -> None:
    with anyio.fail_after(5):
        await verify()


if __name__ == "__main__":
    anyio.run(main)
