from contextlib import AsyncExitStack
from typing import Any

import anyio
import grpc.aio
import pytest
from mcp.client import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.types import CLIENT_CAPABILITIES_META_KEY, CONNECTION_CLOSED, PROTOCOL_VERSION_META_KEY, CallToolRequestParams

from mcp_transport_examples.grpc import grpc_client, grpc_server


@pytest.mark.anyio
@pytest.mark.parametrize("closed_channel", [False, True], ids=["session-exit", "closed-channel-startup"])
async def test_unstarted_and_closed_dispatchers_never_issue_an_rpc(closed_channel: bool) -> None:
    """Public dispatcher guards reject requests before startup and drop notifications after closure without dialing."""
    with anyio.fail_after(5):
        async with (
            grpc.aio.insecure_channel("unused.invalid:50051") as channel,
            grpc_client(channel).connection as dispatcher,
        ):
            with pytest.raises(RuntimeError):
                await dispatcher.send_raw_request("example/test", None)
            with pytest.raises(NoBackChannelError):
                await dispatcher.notify("example/event", None)
            if closed_channel:
                await channel.close()
            async with ClientSession(dispatcher=dispatcher):
                pass
            await dispatcher.notify("example/event", None)
            with pytest.raises(MCPError) as exc:
                await dispatcher.send_raw_request("example/test", None)
        assert exc.value.code == CONNECTION_CLOSED


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["a" * (4 * 1024 * 1024), float("nan")], ids=["oversized", "nonfinite"])
async def test_invalid_outgoing_payload_fails_before_dialing(value: str | float) -> None:
    """The raw dispatcher rejects invalid JSON; the typed client normalizes nonfinite values before this boundary."""
    with anyio.fail_after(5):
        async with (
            grpc.aio.insecure_channel("unused.invalid:50051") as channel,
            grpc_client(channel).connection as dispatcher,
            ClientSession(dispatcher=dispatcher),
        ):
            with pytest.raises(ValueError):
                await dispatcher.send_raw_request("example/test", {"value": value})
            assert channel.get_state() == grpc.ChannelConnectivity.IDLE


@pytest.mark.anyio
async def test_request_ids_preserve_spelling_and_reject_in_flight_collisions() -> None:
    """Exercise the public dispatcher option that the high-level client normally supplies for subscriptions."""
    entered = anyio.Event()
    release = anyio.Event()
    server = MCPServer("request IDs")

    @server.tool()
    async def identify(hold: bool, ctx: Context) -> str | int | None:
        if hold:
            entered.set()
            await release.wait()
        return ctx.request_context.request_id

    waiting = CallToolRequestParams(
        name="identify",
        arguments={"hold": True},
        _meta={PROTOCOL_VERSION_META_KEY: "2026-07-28", CLIENT_CAPABILITIES_META_KEY: {}},
    ).model_dump(by_alias=True, exclude_none=True)
    immediate = CallToolRequestParams(
        name="identify",
        arguments={"hold": False},
        _meta={PROTOCOL_VERSION_META_KEY: "2026-07-28", CLIENT_CAPABILITIES_META_KEY: {}},
    ).model_dump(by_alias=True, exclude_none=True)
    results: list[dict[str, Any]] = []

    with anyio.fail_after(5):
        async with AsyncExitStack() as stack:
            listener = grpc.aio.server()
            port = listener.add_insecure_port("127.0.0.1:0")
            stack.push_async_callback(listener.stop, 0)
            runtime = await stack.enter_async_context(server.serve())
            await runtime.connect(grpc_server(listener))
            await listener.start()
            channel = await stack.enter_async_context(grpc.aio.insecure_channel(f"127.0.0.1:{port}"))
            dispatcher = await stack.enter_async_context(grpc_client(channel).connection)
            await stack.enter_async_context(ClientSession(dispatcher=dispatcher))

            async def first() -> None:
                results.append(await dispatcher.send_raw_request("tools/call", waiting, {"request_id": 0}))

            async with anyio.create_task_group() as tg:
                tg.start_soon(first)
                try:
                    await entered.wait()
                    with pytest.raises(ValueError):
                        await dispatcher.send_raw_request("tools/call", immediate, {"request_id": "0"})
                    minted = await dispatcher.send_raw_request("tools/call", immediate)
                    assert minted["structuredContent"] == {"result": 1}
                finally:
                    release.set()
            assert results[0]["structuredContent"] == {"result": 0}
            reused = await dispatcher.send_raw_request("tools/call", immediate, {"request_id": "0"})
            assert reused["structuredContent"] == {"result": "0"}
