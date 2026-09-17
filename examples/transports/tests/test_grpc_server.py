import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import anyio
import grpc
import grpc.aio
import pytest
from mcp import Client, MCPError
from mcp.client.subscriptions import ToolsListChanged
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CONNECTION_CLOSED, INVALID_PARAMS, Request, RequestParams, Result
from pydantic import BaseModel

from mcp_transport_examples.grpc import grpc_client, grpc_server
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest


@asynccontextmanager
async def serving(server: Server[Any] | MCPServer[Any], *, max_requests: int = 64) -> AsyncIterator[str]:
    async with AsyncExitStack() as stack:
        listener = grpc.aio.server(options=[("grpc.max_receive_message_length", 8 * 1024 * 1024)])
        port = listener.add_insecure_port("127.0.0.1:0")
        stack.push_async_callback(listener.stop, 0)
        runtime = await stack.enter_async_context(server.serve())
        await runtime.connect(grpc_server(listener, max_requests=max_requests))
        await listener.start()
        yield f"127.0.0.1:{port}"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("params", "request_id"),
    [
        (b"[]", b"0"),
        (b'{"number": NaN}', b"0"),
        (b'{"number": 1e400}', b"0"),
        (b"[" * 10_000 + b"0" + b"]" * 10_000, b"0"),
        (b"\xff", b"0"),
        (b"{}", b"true"),
        (b"{}", b"null"),
        (b'{"padding":"' + b"a" * (4 * 1024 * 1024) + b'"}', b"0"),
    ],
    ids=["array", "nonfinite", "overflow", "deep", "invalid-utf8", "boolean-id", "null-id", "oversized"],
)
async def test_invalid_binding_payload_is_rejected_before_mcp_dispatch(params: bytes, request_id: bytes) -> None:
    """The typed MCP client cannot emit malformed protobuf-binding input, so send it over a real raw gRPC call."""
    with anyio.fail_after(5):
        async with serving(Server("validation")) as target, grpc.aio.insecure_channel(target) as channel:
            call = channel.unary_stream(
                "/mcp.transport.example.MCP/Call",
                request_serializer=CallRequest.SerializeToString,
                response_deserializer=CallEvent.FromString,
            )
            with pytest.raises(grpc.aio.AioRpcError) as exc:
                async for _ in call(
                    CallRequest(method="example/invalid", params_json=params, request_id_json=request_id)
                ):
                    raise NotImplementedError
            assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.anyio
async def test_native_capacity_rejects_excess_work_and_recovers() -> None:
    """A saturated binding refuses another request without preventing the admitted one from completing."""
    entered = anyio.Event()
    release = anyio.Event()
    server = MCPServer("capacity")

    @server.tool()
    async def hold() -> str:
        entered.set()
        await release.wait()
        return "released"

    with anyio.fail_after(5):
        async with serving(server, max_requests=1) as target, grpc.aio.insecure_channel(target) as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:

                async def first() -> None:
                    result = await client.call_tool("hold")
                    assert result.structured_content == {"result": "released"}

                async with anyio.create_task_group() as tg:
                    tg.start_soon(first)
                    try:
                        await entered.wait()
                        with pytest.raises(MCPError) as exc:
                            await client.list_tools()
                        assert exc.value.code == CONNECTION_CLOSED
                        cause = exc.value.__cause__
                        assert isinstance(cause, grpc.aio.AioRpcError)
                        assert cause.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
                    finally:
                        release.set()
                tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == ["hold"]


@pytest.mark.anyio
async def test_closed_runtime_refuses_calls_on_a_borrowed_listener() -> None:
    """Runtime shutdown closes the MCP binding while leaving the caller's gRPC listener under its ownership."""
    listener = grpc.aio.server()
    port = listener.add_insecure_port("127.0.0.1:0")
    with anyio.fail_after(5):
        try:
            async with Server("closed runtime").serve() as runtime:
                await runtime.connect(grpc_server(listener))
                await listener.start()
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                async with Client(grpc_client(channel), mode="2026-07-28") as client:
                    with pytest.raises(MCPError) as exc:
                        await client.list_tools()
                    assert exc.value.code == CONNECTION_CLOSED
                    cause = exc.value.__cause__
                    assert isinstance(cause, grpc.aio.AioRpcError)
                    assert cause.code() == grpc.StatusCode.UNAVAILABLE
        finally:
            await listener.stop(0)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["mcp", "validation", "self-cancel"])
async def test_handler_failures_settle_the_native_call(failure: str) -> None:
    """Run the current server's failure paths; a replayed response would not exercise handler lifetime or conversion."""

    class IntegerValue(BaseModel):
        value: int

    async def handler(ctx: ServerRequestContext, params: RequestParams) -> Result:
        assert ctx.method == "example/fail"
        if failure == "mcp":
            raise MCPError(code=12345, message="refused", data={"reason": "application"})
        if failure == "self-cancel":
            raise anyio.get_cancelled_exc_class()()
        IntegerValue.model_validate({"value": "not an integer"})
        raise NotImplementedError

    server = Server("failures")
    server.add_request_handler("example/fail", RequestParams, handler)
    with anyio.fail_after(5):
        async with serving(server) as target, grpc.aio.insecure_channel(target) as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:
                with pytest.raises(MCPError) as exc:
                    await client.session.send_request(Request(method="example/fail", params=RequestParams()), Result)
            assert (
                exc.value.code
                == {"mcp": 12345, "validation": INVALID_PARAMS, "self-cancel": CONNECTION_CLOSED}[failure]
            )


@pytest.mark.anyio
async def test_null_parameters_reach_mcp_envelope_validation() -> None:
    """Null is valid in the binding but lacks the MCP envelope, which the typed client normally always supplies."""
    with anyio.fail_after(5):
        async with serving(Server("envelope")) as target, grpc.aio.insecure_channel(target) as channel:
            call = channel.unary_stream(
                "/mcp.transport.example.MCP/Call",
                request_serializer=CallRequest.SerializeToString,
                response_deserializer=CallEvent.FromString,
            )
            events = [
                event
                async for event in call(CallRequest(method="example/test", params_json=b"null", request_id_json=b"0"))
            ]
            assert len(events) == 1
            assert events[0].WhichOneof("payload") == "error_json"
            assert json.loads(events[0].error_json)["code"] == INVALID_PARAMS


@pytest.mark.anyio
async def test_progress_callback_failure_does_not_abort_the_request(caplog: pytest.LogCaptureFixture) -> None:
    """A client callback failure is isolated from the server result and logged with its traceback."""
    server = MCPServer("callback isolation")

    @server.tool()
    async def ready(ctx: Context) -> str:
        await ctx.report_progress(1.5, 2, "working")
        return "ready"

    async def progress(progress: float, total: float | None, message: str | None) -> None:
        raise RuntimeError("callback failed")

    with anyio.fail_after(5):
        async with serving(server) as target, grpc.aio.insecure_channel(target) as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:
                result = await client.call_tool("ready", progress_callback=progress)
            assert result.structured_content == {"result": "ready"}
    records = [record for record in caplog.records if record.name == "mcp_transport_examples.grpc_response"]
    assert len(records) == 1
    assert records[0].exc_info is not None


@pytest.mark.anyio
async def test_subscription_acknowledgment_and_events_use_the_original_rpc() -> None:
    """A live listen RPC remains open while a separate tool request publishes a typed change event."""
    server = MCPServer("subscriptions")

    @server.tool()
    async def announce(ctx: Context) -> str:
        await ctx.notify_tools_changed()
        return "announced"

    with anyio.fail_after(5):
        async with serving(server) as target, grpc.aio.insecure_channel(target) as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:
                async with client.listen(tools_list_changed=True) as subscription:
                    result = await client.call_tool("announce")
                    assert result.structured_content == {"result": "announced"}
                    event = await anext(subscription)
            assert isinstance(event, ToolsListChanged)


@pytest.mark.anyio
async def test_invalid_capacity_fails_before_registering_the_binding() -> None:
    """Invalid configuration fails locally, without creating an RPC or binding a listening socket."""
    listener = grpc.aio.server()
    with anyio.fail_after(5), pytest.raises(ValueError):
        async with grpc_server(listener, max_requests=0).connection:
            raise NotImplementedError
