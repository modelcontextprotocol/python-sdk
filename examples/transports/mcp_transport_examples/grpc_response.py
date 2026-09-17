"""Consume native response streams and deliver request-scoped notifications."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass, field

import anyio
import grpc.aio
from mcp.shared.dispatcher import CallOptions, OnNotify, OnNotifyIntercept, run_notify_intercept
from mcp.types import ProgressNotificationParams

from mcp_transport_examples._grpc_codec import decode_object
from mcp_transport_examples.grpc_context import GRPCDispatchContext
from mcp_transport_examples.rpc_pb2 import CallEvent, CallRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingCall:
    """Track both the native RPC and callbacks executing in its caller's task."""

    call: grpc.aio.UnaryStreamCall[CallRequest, CallEvent]
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    done: anyio.Event = field(default_factory=anyio.Event)


async def receive_response(
    events: AsyncIterable[CallEvent],
    context: GRPCDispatchContext,
    opts: CallOptions,
    on_notify: OnNotify,
    intercept: OnNotifyIntercept | None,
) -> CallEvent:
    """Deliver notifications in receive order, then require exactly one terminal event followed by EOF."""
    terminal: CallEvent | None = None
    async for event in events:
        kind = event.WhichOneof("payload")
        if terminal is not None or kind is None:
            raise ValueError("Invalid gRPC response sequence")
        if kind != "notification":
            terminal = event
            continue
        notification = event.notification
        data = decode_object(notification.params_json, nullable=True)
        if notification.method == "notifications/progress" and "on_progress" in opts:
            progress = ProgressNotificationParams.model_validate(data, by_name=False)
            try:
                await opts["on_progress"](progress.progress, progress.total, progress.message)
            except Exception:
                logger.exception("Progress callback failed")
        if not run_notify_intercept(intercept, notification.method, data):
            await on_notify(context, notification.method, data)
    if terminal is None:
        raise ValueError("gRPC call ended without an MCP result")
    return terminal
