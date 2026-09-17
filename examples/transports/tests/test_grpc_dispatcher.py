from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import anyio
import grpc.aio
import pytest
from mcp.shared.dispatcher import DispatchContext, Dispatcher, OnNotify, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.transport import TransportContext
from mcp.types import CONNECTION_CLOSED, INTERNAL_ERROR

from mcp_transport_examples.grpc import grpc_client, grpc_server


@asynccontextmanager
async def connected(on_request: OnRequest, on_notify: OnNotify) -> AsyncIterator[Dispatcher[TransportContext]]:
    listener = grpc.aio.server()
    port = listener.add_insecure_port("127.0.0.1:0")
    try:
        async with AsyncExitStack() as stack:
            server = await stack.enter_async_context(grpc_server(listener).connection)
            channel = await stack.enter_async_context(grpc.aio.insecure_channel(f"127.0.0.1:{port}"))
            client = await stack.enter_async_context(grpc_client(channel).connection)
            async with anyio.create_task_group() as tg:
                await tg.start(server.run, on_request, on_notify)
                await tg.start(client.run, on_request, on_notify)
                await listener.start()
                try:
                    yield client
                finally:
                    tg.cancel_scope.cancel()
    finally:
        with anyio.fail_after(5, shield=True):
            await listener.stop(0)


@pytest.mark.anyio
async def test_dispatcher_contains_notification_handler_errors(caplog: pytest.LogCaptureFixture) -> None:
    """The raw dispatcher boundary must contain callbacks even without ClientSession's own containment."""

    async def handler(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        assert method == "example/callback"
        await ctx.notify("example/event", None)
        return {"completed": True}

    async def notification(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> None:
        assert method == "example/event"
        raise RuntimeError("notification failed")

    with anyio.fail_after(5):
        async with connected(handler, notification) as client:
            result = await client.send_raw_request("example/callback", None)
        assert result == {"completed": True}
    records = [record for record in caplog.records if record.name == "mcp_transport_examples.grpc_response"]
    assert len(records) == 1
    assert records[0].exc_info is not None


@pytest.mark.anyio
async def test_dispatcher_sanitizes_unmapped_request_errors() -> None:
    """Test the raw OnRequest boundary because ServerRuntime already maps ordinary handler failures itself."""
    secret = "private handler details"

    async def handler(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        assert method == "example/failure"
        raise RuntimeError(secret)

    async def notification(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> None:
        raise NotImplementedError

    with anyio.fail_after(5):
        async with connected(handler, notification) as client:
            with pytest.raises(MCPError) as exc:
                await client.send_raw_request("example/failure", None)
        assert exc.value.code == INTERNAL_ERROR
        assert secret not in exc.value.message
        assert exc.value.data is None


@pytest.mark.anyio
async def test_request_context_drops_notifications_after_handler_return() -> None:
    """A retained public DispatchContext must not write beyond its RPC's terminal event."""
    contexts: list[DispatchContext[TransportContext]] = []
    notifications: list[str] = []

    async def handler(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        assert method == "example/context"
        contexts.append(ctx)
        await ctx.notify("example/before", None)
        return {"completed": True}

    async def notification(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> None:
        notifications.append(method)

    with anyio.fail_after(5):
        async with connected(handler, notification) as client:
            result = await client.send_raw_request("example/context", None)
            await contexts[0].notify("example/after", None)
        assert result == {"completed": True}
    assert notifications == ["example/before"]


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["progressToken", "progress", None])
async def test_progress_validation_precedes_callbacks(field: str | None) -> None:
    """A raw peer can send invalid booleans; valid progress reaches its callback and the notification observer once."""
    updates: list[float] = []
    observed: list[str] = []

    async def handler(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        assert method == "example/progress"
        data: dict[str, Any] = {"progressToken": "token", "progress": 1}
        if field is not None:
            data[field] = True
        await ctx.notify("notifications/progress", data)
        return {}

    async def notification(
        ctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> None:
        observed.append(method)

    async def progress(progress: float, total: float | None, message: str | None) -> None:
        updates.append(progress)

    with anyio.fail_after(5):
        async with connected(handler, notification) as client:
            if field is None:
                result = await client.send_raw_request("example/progress", None, {"on_progress": progress})
                assert result == {}
            else:
                with pytest.raises(MCPError) as exc:
                    await client.send_raw_request("example/progress", None, {"on_progress": progress})
                assert exc.value.code == CONNECTION_CLOSED
    assert updates == ([1] if field is None else [])
    assert observed == (["notifications/progress"] if field is None else [])
