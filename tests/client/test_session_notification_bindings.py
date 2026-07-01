"""`ClientSession` notification bindings: serialized per-binding delivery through a
bounded FIFO, consulted only for methods the negotiated version's core tables do
not know."""

import logging

import anyio
import mcp_types as types
import pytest
from mcp_types import EmptyResult, Implementation, ServerCapabilities
from mcp_types.version import LATEST_MODERN_VERSION
from pydantic import BaseModel

from mcp.client.extension import NotificationBinding
from mcp.client.session import _NOTIFICATION_QUEUE_SIZE, ClientSession
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.transport_context import TransportContext

_VENDOR_METHOD = "notifications/vendor/task_done"


class _EventParams(BaseModel):
    seq: int


async def _server_on_request(
    ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
) -> dict[str, object]:
    assert method == "ping"
    return {}


async def _server_on_notify(
    ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
) -> None:
    raise NotImplementedError


def _adopt_modern(session: ClientSession) -> None:
    session.adopt(
        types.DiscoverResult(
            supported_versions=[LATEST_MODERN_VERSION],
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="stub", version="0"),
        )
    )


async def _noop_handler(params: _EventParams) -> None:
    raise NotImplementedError  # construction-only tests never deliver


def test_duplicate_binding_method_rejected() -> None:
    """SDK-defined: two bindings on one wire method cannot be routed apart, so construction fails."""
    client_side, _ = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=_noop_handler)

    with pytest.raises(ValueError) as exc_info:
        ClientSession(dispatcher=client_side, notification_bindings=[binding, binding])

    assert str(exc_info.value) == "duplicate notification binding for method 'notifications/vendor/task_done'"


@pytest.mark.anyio
async def test_bound_vendor_notifications_are_delivered_in_order() -> None:
    """SDK-defined: one consumer per binding delivers events in the order the server sent them."""
    delivered: list[int] = []
    done = anyio.Event()

    async def on_event(params: _EventParams) -> None:
        delivered.append(params.seq)
        if params.seq == 3:
            done.set()

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=on_event)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                for seq in (1, 2, 3):
                    await server_side.notify(_VENDOR_METHOD, {"seq": seq})
                await done.wait()
            server_side.close()

    assert delivered == [1, 2, 3]


@pytest.mark.anyio
async def test_binding_handler_may_do_session_io_without_deadlock() -> None:
    """SDK-defined: delivery is spawn-decoupled, so a handler may await session I/O without deadlock."""
    pongs: list[EmptyResult] = []
    done = anyio.Event()

    client_side, server_side = create_direct_dispatcher_pair()

    async def on_event(params: _EventParams) -> None:
        pongs.append(await session.send_ping())
        done.set()

    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=on_event)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                await server_side.notify(_VENDOR_METHOD, {"seq": 1})
                await done.wait()
            server_side.close()

    assert pongs == [EmptyResult()]


@pytest.mark.anyio
async def test_overflow_drops_oldest_event_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: on overflow the bounded FIFO drops the oldest queued event with a
    warning; everything still queued delivers in order."""
    delivered: list[int] = []
    consumer_blocked = anyio.Event()
    gate = anyio.Event()
    done = anyio.Event()
    last_seq = _NOTIFICATION_QUEUE_SIZE + 1

    async def on_event(params: _EventParams) -> None:
        delivered.append(params.seq)
        if params.seq == 0:
            consumer_blocked.set()
            await gate.wait()
        if params.seq == last_seq:
            done.set()

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=on_event)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                await server_side.notify(_VENDOR_METHOD, {"seq": 0})
                await consumer_blocked.wait()
                for seq in range(1, last_seq + 1):
                    await server_side.notify(_VENDOR_METHOD, {"seq": seq})
                gate.set()
                await done.wait()
            server_side.close()

    assert delivered == [0, *range(2, last_seq + 1)]
    assert caplog.text.count(f"notification queue for {_VENDOR_METHOD!r} is full") == 1


@pytest.mark.anyio
async def test_invalid_params_are_warned_and_dropped_without_reaching_handler(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: params failing the binding's model are warned and dropped; later valid events deliver."""
    delivered: list[int] = []
    done = anyio.Event()

    async def on_event(params: _EventParams) -> None:
        delivered.append(params.seq)
        done.set()

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=on_event)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                await server_side.notify(_VENDOR_METHOD, {"bogus": "no seq"})
                await server_side.notify(_VENDOR_METHOD, {"seq": 1})
                await done.wait()
            server_side.close()

    assert delivered == [1]
    assert f"Failed to validate notification: {_VENDOR_METHOD}" in caplog.text


@pytest.mark.anyio
async def test_unbound_vendor_notification_keeps_the_debug_drop(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: a vendor method with no binding keeps the debug-log-and-drop behaviour."""
    caplog.set_level(logging.DEBUG, logger="client")

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=_noop_handler)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                await server_side.notify("notifications/vendor/unbound", {"seq": 1})
            server_side.close()

    assert f"dropped 'notifications/vendor/unbound': not defined at {LATEST_MODERN_VERSION}" in caplog.text


@pytest.mark.anyio
async def test_core_known_method_never_reaches_binding_and_warns_once_at_adopt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: a binding for a core-known method never fires and warns once at
    adopt(); the typed callback still runs."""
    logged: list[types.LoggingMessageNotificationParams] = []

    async def logging_callback(params: types.LoggingMessageNotificationParams) -> None:
        logged.append(params)

    async def on_message(params: BaseModel) -> None:
        raise NotImplementedError  # structurally unreachable: core parses the method first

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method="notifications/message", params_type=BaseModel, handler=on_message)
    session = ClientSession(dispatcher=client_side, logging_callback=logging_callback, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                # In-process notify() awaits _on_notify inline, so the typed callback has already run.
                await server_side.notify("notifications/message", {"level": "info", "data": "hello"})
            server_side.close()

    assert [params.data for params in logged] == ["hello"]
    # The bound handler never ran; a delivery would have logged its NotImplementedError.
    assert "notification binding handler" not in caplog.text
    expected = f"notification binding for 'notifications/message' will never fire at {LATEST_MODERN_VERSION}"
    assert caplog.text.count(expected) == 1


@pytest.mark.anyio
async def test_handler_exception_is_contained_and_later_events_deliver(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: a raising handler costs only that delivery; later events still deliver."""
    delivered: list[int] = []
    done = anyio.Event()

    async def on_event(params: _EventParams) -> None:
        if params.seq == 1:
            raise ValueError("handler boom")
        delivered.append(params.seq)
        done.set()

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=on_event)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                _adopt_modern(session)
                await server_side.notify(_VENDOR_METHOD, {"seq": 1})
                await server_side.notify(_VENDOR_METHOD, {"seq": 2})
                await done.wait()
            server_side.close()

    assert delivered == [2]
    assert f"notification binding handler for {_VENDOR_METHOD!r} raised" in caplog.text


@pytest.mark.anyio
async def test_binding_delivery_works_without_adopt() -> None:
    """SDK-defined: bindings deliver pre-handshake, under the default version tables."""
    delivered: list[int] = []
    done = anyio.Event()

    async def on_event(params: _EventParams) -> None:
        delivered.append(params.seq)
        done.set()

    client_side, server_side = create_direct_dispatcher_pair()
    binding = NotificationBinding(method=_VENDOR_METHOD, params_type=_EventParams, handler=on_event)
    session = ClientSession(dispatcher=client_side, notification_bindings=[binding])
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, _server_on_request, _server_on_notify)
            async with session:
                await server_side.notify(_VENDOR_METHOD, {"seq": 7})
                await done.wait()
            server_side.close()

    assert delivered == [7]
