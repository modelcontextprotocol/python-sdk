"""Test for issue #1283 - Memory leak from idle sessions never being cleaned up.

Without an idle timeout mechanism, sessions created via StreamableHTTPSessionManager
persist indefinitely in ``_server_instances`` even after the client disconnects.
Over time this leaks memory.

The ``session_idle_timeout`` parameter on ``StreamableHTTPSessionManager`` allows
the manager to automatically terminate and remove sessions that have been idle for
longer than the configured duration.
"""

import time
from collections.abc import Callable, Coroutine
from typing import Any

import anyio
import pytest
from starlette.types import Message, Scope

from mcp.server.lowlevel import Server
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


def _make_scope() -> Scope:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }


async def _mock_receive() -> Message:  # pragma: no cover
    return {"type": "http.request", "body": b"", "more_body": False}


def _make_send(sent: list[Message]) -> Callable[[Message], Coroutine[Any, Any, None]]:
    async def mock_send(message: Message) -> None:
        sent.append(message)

    return mock_send


def _extract_session_id(sent_messages: list[Message]) -> str:
    for msg in sent_messages:
        if msg["type"] == "http.response.start":  # pragma: no branch
            for name, value in msg.get("headers", []):  # pragma: no branch
                if name.decode().lower() == MCP_SESSION_ID_HEADER.lower():  # pragma: no branch
                    return value.decode()
    raise AssertionError("Session ID not found in response headers")  # pragma: no cover


@pytest.mark.anyio
async def test_idle_session_is_reaped():
    """Session should be removed from _server_instances after idle timeout."""
    app = Server("test-idle-reap")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.15)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        assert session_id in manager._server_instances

        # Wait for the cancel scope deadline to fire
        await anyio.sleep(0.4)

        assert session_id not in manager._server_instances


@pytest.mark.anyio
async def test_activity_resets_idle_timer():
    """Requests during the timeout window should prevent the session from being reaped."""
    app = Server("test-idle-reset")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.3)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        # Simulate ongoing activity by pushing back the idle scope deadline
        transport = manager._server_instances[session_id]
        assert transport.idle_scope is not None
        for _ in range(4):
            await anyio.sleep(0.1)
            transport.idle_scope.deadline = anyio.current_time() + 0.3

        # Session should still be alive because we kept it active
        assert session_id in manager._server_instances

        # Now stop activity and let the timeout expire
        await anyio.sleep(0.6)

        assert session_id not in manager._server_instances


@pytest.mark.anyio
async def test_multiple_sessions_reaped_independently():
    """Each session tracks its own idle timeout independently."""
    app = Server("test-multi-idle")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.15)

    async with manager.run():
        sent1: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent1))
        session_id_1 = _extract_session_id(sent1)

        await anyio.sleep(0.05)
        sent2: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent2))
        session_id_2 = _extract_session_id(sent2)

        assert session_id_1 in manager._server_instances
        assert session_id_2 in manager._server_instances

        # After enough time, both should be reaped
        await anyio.sleep(0.4)

        assert session_id_1 not in manager._server_instances
        assert session_id_2 not in manager._server_instances


def test_session_idle_timeout_rejects_negative():
    """session_idle_timeout must be a positive number."""
    with pytest.raises(ValueError, match="positive number"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=-1)


def test_session_idle_timeout_rejects_zero():
    """session_idle_timeout must be a positive number."""
    with pytest.raises(ValueError, match="positive number"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=0)


def test_session_idle_timeout_rejects_stateless():
    """session_idle_timeout is not supported in stateless mode."""
    with pytest.raises(ValueError, match="not supported in stateless"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=30, stateless=True)


@pytest.mark.anyio
async def test_terminate_idempotency():
    """Calling terminate() multiple times should be safe."""
    transport = StreamableHTTPServerTransport(mcp_session_id="test-idempotent")

    async with transport.connect():
        await transport.terminate()
        assert transport.is_terminated

        # Second call should be a no-op (no exception)
        await transport.terminate()
        assert transport.is_terminated


@pytest.mark.anyio
async def test_no_idle_timeout_sessions_persist():
    """When session_idle_timeout is None (default), sessions persist indefinitely."""
    app = Server("test-no-timeout")
    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        await anyio.sleep(0.3)
        assert session_id in manager._server_instances


@pytest.mark.anyio
async def test_run_server_exits_promptly_after_idle_timeout():
    """The run_server task must exit shortly after the idle timeout fires."""
    app = Server("test-lifecycle")

    task_exited = anyio.Event()
    exit_timestamp: list[float] = []
    original_run = app.run

    async def instrumented_run(*args: Any, **kwargs: Any) -> None:
        try:
            await original_run(*args, **kwargs)
        finally:
            exit_timestamp.append(time.monotonic())
            task_exited.set()

    app.run = instrumented_run  # type: ignore[assignment]

    idle_timeout = 0.5
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=idle_timeout)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)
        assert session_id in manager._server_instances

        pre_reap_time = time.monotonic()

        with anyio.fail_after(idle_timeout * 4):
            await task_exited.wait()

        assert len(exit_timestamp) == 1
        total_elapsed = exit_timestamp[0] - pre_reap_time
        assert total_elapsed < idle_timeout * 3, (
            f"run_server task took {total_elapsed:.3f}s to exit; expected < {idle_timeout * 3:.1f}s"
        )
        assert session_id not in manager._server_instances


@pytest.mark.anyio
async def test_run_server_finally_block_runs_after_terminate():
    """Verify that the finally block in run_server executes after terminate()."""
    app = Server("test-finally")

    lifecycle_events: list[str] = []
    original_run = app.run

    async def instrumented_run(*args: Any, **kwargs: Any) -> None:
        lifecycle_events.append("run_entered")
        try:
            await original_run(*args, **kwargs)
        finally:
            lifecycle_events.append("run_exited")

    app.run = instrumented_run  # type: ignore[assignment]

    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)
        transport = manager._server_instances[session_id]

        assert "run_entered" in lifecycle_events
        assert "run_exited" not in lifecycle_events

        await transport.terminate()

        with anyio.fail_after(3.0):
            while "run_exited" not in lifecycle_events:
                await anyio.sleep(0.01)

        assert "run_exited" in lifecycle_events


@pytest.mark.anyio
async def test_idle_timeout_end_to_end():
    """End-to-end: idle timeout causes session cleanup with a real Server."""
    app = Server("test-e2e")
    idle_timeout = 0.3
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=idle_timeout)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)
        assert session_id in manager._server_instances

        with anyio.fail_after(idle_timeout + 1.0):
            while session_id in manager._server_instances:
                await anyio.sleep(0.05)

        assert session_id not in manager._server_instances
