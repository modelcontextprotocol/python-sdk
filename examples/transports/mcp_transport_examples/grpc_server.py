"""Serve native protobuf RPCs through the SDK's dispatcher interface."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

import anyio
import anyio.abc
import grpc
import grpc.aio
from mcp.server.runner import modern_error_data
from mcp.shared.dispatcher import CallOptions, OnNotify, OnNotifyIntercept, OnRequest, as_request_id
from mcp.shared.exceptions import NoBackChannelError

from mcp_transport_examples._grpc_codec import decode_json, decode_object, encode_json
from mcp_transport_examples.grpc_context import GRPCContext, GRPCDispatchContext
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest, Notification


class GRPCServerDispatcher:
    """Attach MCP to a borrowed gRPC server without taking ownership of its listener.

    Register before starting the server. The runtime starts this dispatcher;
    you start and stop the gRPC server. Each RPC has independent MCP metadata
    and a response stream. Shutdown cancels and joins active request handlers.
    """

    def __init__(self, server: grpc.aio.Server, *, max_requests: int = 64) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self._limit = anyio.CapacityLimiter(max_requests)
        self._handler: OnRequest | None = None
        self._requests: dict[anyio.CancelScope, anyio.Event] = {}
        self._stopped = anyio.Event()
        handler = grpc.unary_stream_rpc_method_handler(
            self.handle, request_deserializer=CallRequest.FromString, response_serializer=CallEvent.SerializeToString
        )
        server.add_generic_rpc_handlers(
            [grpc.method_handlers_generic_handler("mcp.transport.example.MCP", {"Call": handler})]
        )

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Install the MCP handler and wait until runtime shutdown."""
        self._handler = on_request
        task_status.started()
        try:
            await self._stopped.wait()
        finally:
            self._handler = None
            self._stopped.set()
            requests = tuple(self._requests.items())
            for scope, _ in requests:
                scope.cancel()
            with anyio.CancelScope(shield=True):
                for _, done in requests:
                    await done.wait()

    async def handle(self, request: CallRequest, context: grpc.aio.ServicerContext[CallRequest, CallEvent]) -> None:
        """Handle one gRPC call, with native cancellation and request-scoped notification delivery."""
        handler = self._handler
        if handler is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "MCP dispatcher is not running")
        try:
            self._limit.acquire_nowait()
        except anyio.WouldBlock:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "MCP request capacity exhausted")
        scope = anyio.CancelScope()
        done = anyio.Event()
        self._requests[scope] = done
        lock = anyio.Lock()
        notifications_open = True

        async def notify(method: str, params: Mapping[str, Any] | None) -> None:
            async with lock:
                if not notifications_open:
                    return
                await context.write(
                    CallEvent(notification=Notification(method=method, params_json=encode_json(params)))
                )

        try:
            try:
                params = decode_object(request.params_json, nullable=True)
                request_id = as_request_id(decode_json(request.request_id_json))
                if request_id is None:
                    raise ValueError("Invalid request id")
            except (ValueError, UnicodeError):
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid MCP binding payload")
            dctx = GRPCDispatchContext(
                transport=GRPCContext(
                    kind="grpc",
                    can_send_request=False,
                    peer=context.peer(),
                    metadata=cast("tuple[tuple[str, str | bytes], ...]", tuple(context.invocation_metadata() or ())),
                    peer_identity_key=context.peer_identity_key(),
                    peer_identities=tuple(context.peer_identities() or ()),
                ),
                request_id=request_id,
                send_notification=notify,
                report_progress=request.report_progress,
            )

            response: CallEvent | None = None
            ready = anyio.Event()

            async def invoke() -> None:
                nonlocal response, notifications_open
                try:
                    result = await handler(dctx, request.method, params)
                    response = CallEvent(result_json=encode_json(result))
                except Exception as exc:
                    response = CallEvent(error_json=encode_json(modern_error_data(exc).model_dump(by_alias=True)))
                finally:
                    notifications_open = False
                    ready.set()

            with scope:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(invoke)
                    try:
                        await ready.wait()
                    except asyncio.CancelledError:
                        if not scope.cancel_called and not tg.cancel_scope.cancel_called:
                            dctx.cancel_requested.set()
                        raise
                if response is None:
                    await context.abort(grpc.StatusCode.CANCELLED, "MCP handler ended without a result")
                async with lock:
                    await context.write(response)
            if scope.cancelled_caught:
                await context.abort(grpc.StatusCode.UNAVAILABLE, "MCP dispatcher closed")
        finally:
            self._requests.pop(scope)
            done.set()
            self._limit.release()

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        """Reject server-initiated requests in the modern binding."""
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        """Reject notifications without an originating RPC; use its DispatchContext instead."""
        raise NoBackChannelError(method)
