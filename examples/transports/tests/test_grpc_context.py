from collections.abc import Mapping
from typing import Any

import anyio
import grpc.aio
import pytest
from mcp.shared.exceptions import NoBackChannelError

from mcp_transport_examples.grpc import grpc_server
from mcp_transport_examples.grpc_context import GRPCContext, GRPCDispatchContext


@pytest.mark.anyio
async def test_modern_binding_refuses_server_requests_and_unscoped_notifications() -> None:
    """The public dispatcher and context refuse channels that the native modern binding does not provide."""
    listener = grpc.aio.server()

    async def notify(method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    context = GRPCDispatchContext(GRPCContext(kind="grpc", can_send_request=False, peer="test"), 1, notify)
    with anyio.fail_after(5):
        with pytest.raises(NoBackChannelError):
            await context.send_raw_request("example/request", None)
        async with grpc_server(listener).connection as dispatcher:
            with pytest.raises(NoBackChannelError):
                await dispatcher.send_raw_request("example/request", None)
            with pytest.raises(NoBackChannelError):
                await dispatcher.notify("example/event", None)
        assert not context.can_send_request


@pytest.mark.anyio
@pytest.mark.parametrize("report_progress", [False, True])
async def test_context_progress_is_opt_in_and_omits_absent_fields(report_progress: bool) -> None:
    """Progress without an opt-in is a no-op; supplied values are forwarded without inventing total or message."""
    notifications: list[tuple[str, Mapping[str, Any] | None]] = []

    async def notify(method: str, params: Mapping[str, Any] | None) -> None:
        notifications.append((method, params))

    context = GRPCDispatchContext(
        GRPCContext(kind="grpc", can_send_request=False, peer="test"),
        "request",
        notify,
        report_progress=report_progress,
    )
    await context.progress(1)
    assert notifications == (
        [("notifications/progress", {"progressToken": "request", "progress": 1})] if report_progress else []
    )
