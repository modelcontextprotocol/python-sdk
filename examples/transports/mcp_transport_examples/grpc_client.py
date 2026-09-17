"""A native gRPC dispatcher that reuses the SDK's high-level client."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import anyio
import anyio.abc
import grpc
import grpc.aio
from mcp.shared.dispatcher import (
    CallOptions,
    OnNotify,
    OnNotifyIntercept,
    OnRequest,
    coerce_request_id,
)
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, ErrorData, RequestId

from mcp_transport_examples._grpc_codec import RPC_METHOD, decode_object, encode_json
from mcp_transport_examples.grpc_context import GRPCContext, GRPCDispatchContext
from mcp_transport_examples.grpc_response import PendingCall, receive_response
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest


class GRPCClientDispatcher:
    """Run MCP calls on a borrowed gRPC channel, with one response stream per request."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._channel = channel
        self._rpc = channel.unary_stream(
            RPC_METHOD, request_serializer=CallRequest.SerializeToString, response_deserializer=CallEvent.FromString
        )
        self._on_notify: OnNotify | None = None
        self._intercept: OnNotifyIntercept | None = None
        self._calls: dict[RequestId, PendingCall] = {}
        self._next_id = 0
        self._closed = False

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        on_notify_intercept: OnNotifyIntercept | None = None,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """Enable requests and cancel active RPCs when the client session exits."""
        self._on_notify = on_notify
        self._intercept = on_notify_intercept
        task_status.started()
        try:
            state = self._channel.get_state()
            while state != grpc.ChannelConnectivity.SHUTDOWN:
                await self._channel.wait_for_state_change(state)
                state = self._channel.get_state()
        finally:
            self._closed = True
            self._on_notify = None
            pending = tuple(self._calls.values())
            for request in pending:
                request.scope.cancel()
                request.call.cancel()
            with anyio.CancelScope(shield=True):
                for request in pending:
                    await request.done.wait()

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        """Send a native RPC and route its notifications before returning the final result.

        Raises:
            MCPError: A peer error, request timeout, or closed connection.
        """
        if self._closed or self._channel.get_state() == grpc.ChannelConnectivity.SHUTDOWN:
            raise MCPError(code=CONNECTION_CLOSED, message="Connection closed")
        on_notify = self._on_notify
        if on_notify is None:
            raise RuntimeError("GRPCClientDispatcher.run() has not started")
        opts = opts or {}
        request_id = opts.get("request_id")
        if request_id is None:
            while self._next_id in self._calls:
                self._next_id += 1
            request_id = self._next_id
            self._next_id += 1
        key = coerce_request_id(request_id)
        if key in self._calls:
            raise ValueError(f"Request id {request_id!r} is already in flight")
        request = CallRequest(
            method=method,
            params_json=encode_json(params),
            request_id_json=encode_json(request_id),
            report_progress="on_progress" in opts,
        )
        call = self._rpc(request, timeout=opts.get("timeout"))
        pending = PendingCall(call)
        self._calls[key] = pending
        complete = False
        terminal: CallEvent | None = None
        dctx = GRPCDispatchContext(GRPCContext(kind="grpc", can_send_request=False, peer="server"), None, self.notify)
        try:
            with pending.scope, anyio.fail_after(opts.get("timeout")):
                terminal = await receive_response(call, dctx, opts, on_notify, self._intercept)
                complete = True
            if terminal is None:
                raise MCPError(code=CONNECTION_CLOSED, message="Connection closed")
            if terminal.WhichOneof("payload") == "error_json":
                raise MCPError.from_error_data(ErrorData.model_validate(decode_object(terminal.error_json)))
            result = decode_object(terminal.result_json)
            assert result is not None
            return result
        except grpc.aio.AioRpcError as exc:
            code = REQUEST_TIMEOUT if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED else CONNECTION_CLOSED
            raise MCPError(
                code=code, message="gRPC request timed out" if code == REQUEST_TIMEOUT else "gRPC connection failed"
            ) from exc
        except ValueError as exc:
            raise MCPError(code=CONNECTION_CLOSED, message="Invalid gRPC response") from exc
        except TimeoutError as exc:
            raise MCPError(code=REQUEST_TIMEOUT, message="gRPC request timed out") from exc
        except asyncio.CancelledError:
            if self._closed or self._channel.get_state() == grpc.ChannelConnectivity.SHUTDOWN:
                raise MCPError(code=CONNECTION_CLOSED, message="Connection closed") from None
            raise
        finally:
            self._calls.pop(key)
            if not complete:
                call.cancel()
            pending.done.set()

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        """The modern native binding uses structural cancellation, not client notifications."""
        if not self._closed and self._channel.get_state() != grpc.ChannelConnectivity.SHUTDOWN:
            raise NoBackChannelError(method)
