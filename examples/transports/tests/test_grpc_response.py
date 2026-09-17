from collections.abc import AsyncIterator

import anyio
import grpc
import grpc.aio
import pytest
from mcp import Client, MCPError
from mcp.types import CONNECTION_CLOSED, Request, RequestParams, Result

from mcp_transport_examples.grpc import grpc_client
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest, Notification


@pytest.mark.anyio
@pytest.mark.parametrize(
    "events",
    [
        [],
        [CallEvent()],
        [CallEvent(result_json=b"{}"), CallEvent(result_json=b"{}")],
        [CallEvent(result_json=b"[]")],
        [CallEvent(result_json=b'{"value": Infinity}')],
        [CallEvent(result_json=b'{"value": 1e400}')],
        [CallEvent(result_json=b"[" * 10_000 + b"0" + b"]" * 10_000)],
        [CallEvent(notification=Notification(method="example/event", params_json=b"[]"))],
        [
            CallEvent(
                notification=Notification(
                    method="notifications/progress", params_json=b'{"progressToken":0,"progress":1}'
                )
            )
        ],
        [CallEvent(result_json=b'{"padding":"' + b"a" * (4 * 1024 * 1024) + b'"}')],
    ],
    ids=[
        "missing",
        "empty-event",
        "duplicate",
        "array-result",
        "nonfinite",
        "overflow",
        "deep",
        "bad-notification",
        "notification-only",
        "oversized",
    ],
)
async def test_invalid_response_frames_fail_the_mcp_request(events: list[CallEvent]) -> None:
    """A typed SDK server cannot produce these invalid frames, so a local gRPC peer sends them explicitly."""

    async def reply(
        request: CallRequest, context: grpc.aio.ServicerContext[CallRequest, CallEvent]
    ) -> AsyncIterator[CallEvent]:
        assert request.method == "example/response"
        for event in events:
            yield event

    listener = grpc.aio.server()
    listener.add_generic_rpc_handlers(
        [
            grpc.method_handlers_generic_handler(
                "mcp.transport.example.MCP",
                {
                    "Call": grpc.unary_stream_rpc_method_handler(
                        reply,
                        request_deserializer=CallRequest.FromString,
                        response_serializer=CallEvent.SerializeToString,
                    )
                },
            )
        ]
    )
    port = listener.add_insecure_port("127.0.0.1:0")
    with anyio.fail_after(5):
        try:
            await listener.start()
            async with grpc.aio.insecure_channel(
                f"127.0.0.1:{port}", options=[("grpc.max_receive_message_length", 8 * 1024 * 1024)]
            ) as channel:
                async with Client(grpc_client(channel), mode="2026-07-28") as client:
                    with pytest.raises(MCPError) as exc:
                        await client.session.send_request(
                            Request(method="example/response", params=RequestParams()), Result
                        )
                    assert exc.value.code == CONNECTION_CLOSED
                    assert isinstance(exc.value.__cause__, ValueError)
        finally:
            with anyio.fail_after(5, shield=True):
                await listener.stop(0)
