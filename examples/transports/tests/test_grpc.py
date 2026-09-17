import json
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import anyio
import grpc.aio
import pytest
from cassetter import Cassette, Cassetter
from mcp import Client, MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    CONNECTION_CLOSED,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    Request,
    RequestParams,
    Result,
)

from mcp_transport_examples.grpc import grpc_client, grpc_server
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest


@pytest.fixture(scope="module")
def vcr_config() -> Cassetter:
    return Cassetter(intercept=["grpc"])


@asynccontextmanager
async def connected(
    server: Server[Any] | MCPServer[Any], cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Client]:
    async with AsyncExitStack() as stack:
        listener = grpc.aio.server()
        port = listener.add_insecure_port("127.0.0.1:0")
        stack.push_async_callback(listener.stop, 0)
        runtime = await stack.enter_async_context(server.serve())
        await runtime.connect(grpc_server(listener))
        await listener.start()
        channel = await stack.enter_async_context(grpc.aio.insecure_channel(f"127.0.0.1:{port}"))
        requests: list[CallRequest] = []
        unary_stream = channel.unary_stream

        def capture(
            method: str,
            request_serializer: Callable[[CallRequest], bytes] | None = None,
            response_deserializer: Callable[[bytes], CallEvent] | None = None,
        ) -> grpc.aio.UnaryStreamMultiCallable[CallRequest, CallEvent]:
            assert request_serializer is not None

            def serialize(request: CallRequest) -> bytes:
                payload = request_serializer(request)
                requests.append(CallRequest.FromString(payload))
                return payload

            return unary_stream(method, request_serializer=serialize, response_deserializer=response_deserializer)

        monkeypatch.setattr(channel, "unary_stream", capture)
        client = await stack.enter_async_context(Client(grpc_client(channel), mode="2026-07-28"))
        yield client
        assert requests
        assert len(cassette.grpc_interactions) == 1
        payload = cassette.grpc_interactions[0].request.body.content
        assert isinstance(payload, bytes)
        recorded = CallRequest.FromString(payload)
        for request in requests:
            # cassetter currently matches gRPC methods, not request bodies.
            assert request.method == recorded.method
            assert json.loads(request.params_json) == json.loads(recorded.params_json)
            assert request.request_id_json == recorded.request_id_json
            assert request.report_progress == recorded.report_progress


@pytest.mark.anyio
@pytest.mark.vcr
async def test_native_payload_keeps_large_integers_and_extension_fields(
    cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded real RPC preserves arbitrary MCP payload fields without protobuf Struct's float conversion."""

    class EchoParams(RequestParams):
        value: dict[str, Any]

    class EchoResult(Result):
        value: dict[str, Any]

    async def echo(ctx: ServerRequestContext, params: EchoParams) -> EchoResult:
        assert ctx.method == "example/echo"
        return EchoResult(value=params.value)

    server = Server("native")
    server.add_request_handler("example/echo", EchoParams, echo)
    payload = {"large": 2**63 + 1, "vendor/field": [None, {"label": "café"}]}
    with anyio.fail_after(5):
        async with connected(server, cassette, monkeypatch) as client:
            result = await client.session.send_request(
                Request(method="example/echo", params=EchoParams(value=payload)), EchoResult
            )
            assert result.value == payload
        async with Client(server, mode="2026-07-28") as local:
            expected = await local.session.send_request(
                Request(method="example/echo", params=EchoParams(value=payload)), EchoResult
            )
        assert result == expected


@pytest.mark.anyio
@pytest.mark.vcr
async def test_native_progress_reaches_the_client_before_the_result(
    cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded response stream routes progress through the SDK callback, isolated from tools/list schema fetching."""
    server = MCPServer("native-progress")

    @server.tool()
    async def echo(value: str, ctx: Context) -> str:
        await ctx.report_progress(1, 2, "halfway")
        return value

    updates: list[tuple[float, float | None, str | None]] = []

    async def progress(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))

    value = "native progress"
    with anyio.fail_after(5):
        async with connected(server, cassette, monkeypatch) as client:
            result = await client.session.send_request(
                CallToolRequest(params=CallToolRequestParams(name="echo", arguments={"value": value})),
                CallToolResult,
                progress_callback=progress,
            )
            assert result.structured_content == {"result": value}
        wire_updates = updates.copy()
        updates.clear()
        async with Client(server, mode="2026-07-28") as local:
            expected = await local.session.send_request(
                CallToolRequest(params=CallToolRequestParams(name="echo", arguments={"value": value})),
                CallToolResult,
                progress_callback=progress,
            )
        assert result == expected
    assert updates == wire_updates == [(1, 2, "halfway")]


@pytest.mark.anyio
async def test_request_immediately_after_channel_close_reports_mcp_connection_closed() -> None:
    """An idle borrowed channel closes without a network request or a scheduling opportunity for its watcher."""
    with anyio.fail_after(5):
        async with grpc.aio.insecure_channel("unused.invalid:50051") as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:
                await channel.close()
                with pytest.raises(MCPError) as exc:
                    await client.list_tools()
            assert exc.value.code == CONNECTION_CLOSED


@pytest.mark.anyio
@pytest.mark.vcr
async def test_native_error_keeps_code_message_and_data(cassette: Cassette, monkeypatch: pytest.MonkeyPatch) -> None:
    """Native application errors retain all MCP fields, including codes outside signed int32."""
    code = -(2**40)
    message = "application refusal"
    data = {"vendor/reason": "capacity", "large": 2**63 + 1}

    async def refuse(ctx: ServerRequestContext, params: RequestParams) -> Result:
        assert ctx.method == "example/refuse"
        raise MCPError(code=code, message=message, data=data)

    server = Server("native-errors")
    server.add_request_handler("example/refuse", RequestParams, refuse)
    with anyio.fail_after(5):
        async with connected(server, cassette, monkeypatch) as client:
            with pytest.raises(MCPError) as exc:
                await client.session.send_request(Request(method="example/refuse", params=RequestParams()), Result)
            assert exc.value.code == code
            assert exc.value.message == message
            assert exc.value.data == data
        async with Client(server, mode="2026-07-28") as local:
            with pytest.raises(MCPError) as expected:
                await local.session.send_request(Request(method="example/refuse", params=RequestParams()), Result)
        assert exc.value.error == expected.value.error
