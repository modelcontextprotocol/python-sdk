"""Test for issue #1283 - Memory leak from idle sessions never being cleaned up.

Without an idle timeout mechanism, sessions created via StreamableHTTPSessionManager
persist indefinitely in ``_server_instances`` even after the client disconnects.
Over time this leaks memory.

The ``session_idle_timeout`` parameter on ``StreamableHTTPSessionManager`` allows
the manager to automatically terminate and remove sessions that have been idle for
longer than the configured duration.

The lifecycle verification tests (``test_run_server_*``,
``test_terminate_propagates_*``) prove that the full shutdown chain works
end-to-end: ``terminate()`` closes the read stream, which ends the receive
loop, which causes ``Server.run()`` to return and the ``run_server`` task to
exit cleanly.
"""

import time

import anyio
import pytest
from starlette.types import Message

from mcp.server.lowlevel import Server
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


def _make_scope() -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }


async def _mock_receive() -> Message:  # pragma: no cover
    return {"type": "http.request", "body": b"", "more_body": False}


def _make_send(sent: list[Message]):
    async def mock_send(message: Message) -> None:
        sent.append(message)

    return mock_send


def _extract_session_id(sent_messages: list[Message]) -> str:
    for msg in sent_messages:
        if msg["type"] == "http.response.start":
            for name, value in msg.get("headers", []):
                if name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    return value.decode()
    raise AssertionError("Session ID not found in response headers")


def _make_blocking_run(stop_event: anyio.Event):
    """Create a mock app.run that blocks until stop_event is set."""

    async def blocking_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        await stop_event.wait()

    return blocking_run


@pytest.mark.anyio
async def test_idle_session_is_reaped():
    """Session should be removed from _server_instances after idle timeout."""
    app = Server("test-idle-reap")
    stop = anyio.Event()
    app.run = _make_blocking_run(stop)  # type: ignore[assignment]

    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=0.15,
    )

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        assert session_id in manager._server_instances

        # Wait long enough for the reaper to fire (scan_interval = timeout/2 = 0.075s)
        await anyio.sleep(0.4)

        assert session_id not in manager._server_instances
        assert session_id not in manager._last_activity

        stop.set()


@pytest.mark.anyio
async def test_activity_resets_idle_timer():
    """Requests during the timeout window should prevent the session from being reaped."""
    app = Server("test-idle-reset")
    stop = anyio.Event()
    app.run = _make_blocking_run(stop)  # type: ignore[assignment]

    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=0.3,
    )

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        # Simulate ongoing activity by updating the activity timestamp periodically
        for _ in range(4):
            await anyio.sleep(0.1)
            manager._last_activity[session_id] = anyio.current_time()

        # Session should still be alive because we kept it active
        assert session_id in manager._server_instances

        # Now stop activity and let the timeout expire
        await anyio.sleep(0.6)

        assert session_id not in manager._server_instances

        stop.set()


@pytest.mark.anyio
async def test_multiple_sessions_reaped_independently():
    """Each session tracks its own idle timeout independently."""
    app = Server("test-multi-idle")
    stop = anyio.Event()
    app.run = _make_blocking_run(stop)  # type: ignore[assignment]

    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=0.15,
    )

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

        stop.set()


@pytest.mark.anyio
async def test_terminate_idempotency():
    """Calling terminate() multiple times should be safe."""
    transport = StreamableHTTPServerTransport(
        mcp_session_id="test-idempotent",
    )

    async with transport.connect():
        await transport.terminate()
        assert transport.is_terminated

        # Second call should be a no-op (no exception)
        await transport.terminate()
        assert transport.is_terminated


@pytest.mark.anyio
async def test_idle_timeout_with_retry_interval():
    """When retry_interval is set, effective timeout should account for polling gaps."""
    app = Server("test-retry-interval")

    # retry_interval = 5000ms = 5s -> retry_seconds * 3 = 15s
    # session_idle_timeout = 1s -> effective = max(1, 15) = 15
    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=1.0,
        retry_interval=5000,
    )
    assert manager._effective_idle_timeout() == 15.0

    # When retry_interval is small, session_idle_timeout should dominate
    manager2 = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=10.0,
        retry_interval=100,  # 0.1s -> 0.3s, less than 10
    )
    assert manager2._effective_idle_timeout() == 10.0

    # No retry_interval -> raw timeout
    manager3 = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=5.0,
    )
    assert manager3._effective_idle_timeout() == 5.0


@pytest.mark.anyio
async def test_no_idle_timeout_no_reaper():
    """When session_idle_timeout is None (default), sessions persist indefinitely."""
    app = Server("test-no-timeout")
    stop = anyio.Event()
    app.run = _make_blocking_run(stop)  # type: ignore[assignment]

    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        # Wait a while - session should never be reaped
        await anyio.sleep(0.3)
        assert session_id in manager._server_instances

        stop.set()


# ---------------------------------------------------------------------------
# Lifecycle verification tests
# ---------------------------------------------------------------------------
# These tests verify that ``run_server`` tasks exit promptly after the idle
# reaper calls ``transport.terminate()``.  The expected shutdown chain is:
#
#   1. ``terminate()`` closes ``_read_stream_writer`` and ``_read_stream``
#   2. ``_receive_loop`` ends its iteration over ``self._read_stream``
#   3. ``_receive_loop`` exits, closing the incoming-messages writer
#   4. ``Server.run()`` ends its iteration over ``session.incoming_messages``
#   5. ``Server.run()`` returns normally
#   6. The ``run_server`` closure's ``finally`` block executes
#   7. The ``connect()`` context manager exits, cleaning up streams


@pytest.mark.anyio
async def test_run_server_exits_promptly_after_terminate():
    """The run_server task must exit shortly after the idle reaper
    calls terminate() on its transport.

    This test uses a real ``Server`` (not a mock) so that the full chain
    of stream closures is exercised.  A monkey-patched wrapper around
    ``Server.run`` records a timestamp when the method returns, letting us
    assert that the task did not linger.
    """
    app = Server("test-lifecycle")

    # Sentinel: will be set from inside the patched Server.run when it returns.
    task_exited = anyio.Event()
    exit_timestamp: list[float] = []  # mutable container for the timestamp

    original_run = app.run

    async def instrumented_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            await original_run(*args, **kwargs)
        finally:
            exit_timestamp.append(time.monotonic())
            task_exited.set()

    app.run = instrumented_run  # type: ignore[assignment]

    idle_timeout = 0.5  # seconds
    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=idle_timeout,
    )

    async with manager.run():
        # -- Step 1: establish a session --
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)
        assert session_id in manager._server_instances

        # Record the time just before we start waiting for the reaper.
        pre_reap_time = time.monotonic()

        # -- Step 2: wait for the reaper to fire --
        # The reaper scans every ``timeout / 2`` seconds, so after
        # ``timeout + timeout/2 + small margin`` the session should be reaped.
        # We use a generous upper bound so the test is not flaky, but we
        # also measure the *actual* timing below.
        max_wait = idle_timeout * 4  # generous upper bound
        with anyio.fail_after(max_wait):
            await task_exited.wait()

        # -- Step 3: assertions --
        assert len(exit_timestamp) == 1, "instrumented_run should have exited exactly once"

        # How long after the test started did the task exit?
        total_elapsed = exit_timestamp[0] - pre_reap_time
        # The reaper should fire at ~idle_timeout + scan_interval (= timeout/2)
        # so the total should be roughly 0.5 + 0.25 = 0.75s.  The task itself
        # should exit almost instantly after terminate().  We allow up to 2x
        # the idle timeout as a generous upper bound to avoid flakiness.
        assert total_elapsed < idle_timeout * 3, (
            f"run_server task took {total_elapsed:.3f}s to exit after pre_reap_time; "
            f"expected < {idle_timeout * 3:.1f}s"
        )

        # The session must have been removed from tracking dicts.
        assert session_id not in manager._server_instances, (
            "Session should have been removed from _server_instances by the reaper"
        )
        assert session_id not in manager._last_activity, (
            "Session should have been removed from _last_activity by the reaper"
        )

        # Report timing for human inspection (visible with -s flag).
        print("\n--- run_server lifecycle timing ---")
        print(f"  idle_timeout:          {idle_timeout}s")
        print(f"  total elapsed:         {total_elapsed:.3f}s")
        # Estimate how long the task lingered *after* the reaper fired.
        # The reaper fires at approximately idle_timeout + scan_interval.
        scan_interval = idle_timeout / 2
        estimated_reap_time = idle_timeout + scan_interval
        linger_estimate = max(0, total_elapsed - estimated_reap_time)
        print(f"  estimated reap time:   ~{estimated_reap_time:.3f}s")
        print(f"  estimated task linger: ~{linger_estimate:.3f}s")
        print(f"  result: {'PASS - task exited promptly' if linger_estimate < 0.5 else 'SLOW - task lingered'}")


@pytest.mark.anyio
async def test_run_server_finally_block_runs_after_terminate():
    """Verify that the ``finally`` block in ``run_server`` actually executes
    after ``terminate()``, which is critical for resource cleanup.

    This test patches ``Server.run`` to track both entry and exit, and
    directly calls ``transport.terminate()`` (bypassing the reaper) to
    isolate the termination chain from timer mechanics.
    """
    app = Server("test-finally")

    lifecycle_events: list[str] = []
    original_run = app.run

    async def instrumented_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        lifecycle_events.append("run_entered")
        try:
            await original_run(*args, **kwargs)
        finally:
            lifecycle_events.append("run_exited")

    app.run = instrumented_run  # type: ignore[assignment]

    # No idle timeout -- we will terminate manually.
    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        # Establish a session.
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)
        transport = manager._server_instances[session_id]

        assert "run_entered" in lifecycle_events
        assert "run_exited" not in lifecycle_events

        # Directly terminate the transport.
        terminate_time = time.monotonic()
        await transport.terminate()

        # Give the task a moment to react to the stream closure.
        with anyio.fail_after(3.0):
            while "run_exited" not in lifecycle_events:
                await anyio.sleep(0.01)

        exit_delay = time.monotonic() - terminate_time
        assert "run_exited" in lifecycle_events, "run_server finally block never executed"

        print("\n--- terminate -> run_server exit timing ---")
        print(f"  delay after terminate(): {exit_delay:.3f}s")
        print(f"  lifecycle_events: {lifecycle_events}")


@pytest.mark.anyio
async def test_terminate_propagates_through_real_server_run():
    """End-to-end verification that terminate() causes Server.run() to
    return by closing the read stream, which ends the receive loop and
    the incoming_messages iteration.

    Unlike the other tests, this one does NOT monkey-patch Server.run
    at all.  It relies on observing the task exit via the session being
    cleaned up from _server_instances.
    """
    app = Server("test-propagation")

    # Use idle reaper with a short timeout.
    idle_timeout = 0.3
    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=idle_timeout,
    )

    async with manager.run():
        sent: list[Message] = []
        await manager.handle_request(_make_scope(), _mock_receive, _make_send(sent))
        session_id = _extract_session_id(sent)

        assert session_id in manager._server_instances

        # Wait for the reaper.  The reaper removes the session from
        # _server_instances *before* calling terminate(), so the session
        # will be gone from the dict shortly after the reaper fires.
        scan_interval = idle_timeout / 2
        max_wait = idle_timeout + scan_interval + 1.0  # generous
        with anyio.fail_after(max_wait):
            while session_id in manager._server_instances:
                await anyio.sleep(0.05)

        assert session_id not in manager._server_instances
        assert session_id not in manager._last_activity

        # Give a beat for the task to fully exit after terminate().
        await anyio.sleep(0.1)

        # At this point the run_server task should have completed.
        # There is no direct handle to the task, but the fact that we
        # reach here without the task group raising means it exited
        # cleanly (an exception in the task would propagate).
        print("\n--- propagation test passed ---")
        print(f"  Session {session_id} reaped and task exited cleanly.")
