# ExceptionGroup Unwrapping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unwrap `BaseExceptionGroup` exceptions from anyio task groups, exposing only the real error to callers instead of wrapping it with `CancelledError` from cancelled sibling tasks.

**Architecture:**
1. Create a utility function to unwrap ExceptionGroups, extracting only non-cancelled exceptions
2. Wrap all `create_task_group()` usages to catch and unwrap ExceptionGroups before propagating
3. Add tests to verify errors are unwrapped properly

**Tech Stack:** anyio, pytest, Python 3.10+

---

## Task 1: Create ExceptionGroup Unwrapping Utility

**Files:**
- Create: `src/mcp/shared/exceptions.py` (add to existing file)

**Step 1: Write failing test for the unwrapping utility**

Create file: `tests/shared/test_exceptions.py`

```python
"""Tests for exception utilities."""
from __future__ import annotations

import anyio
import pytest

from mcp.shared.exceptions import unwrap_task_group_exception


class CustomError(Exception):
    """A custom error for testing."""


async def test_unwrap_single_error():
    """Test that a single exception is returned as-is."""
    error = ValueError("test error")
    result = unwrap_task_group_exception(error)
    assert result is error


async def test_unwrap_exception_group_with_real_error():
    """Test that real error is extracted from ExceptionGroup."""
    real_error = ConnectionError("connection failed")

    # Simulate what anyio does: create exception group with real error + cancelled
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: (_ for _ in ()).throw(real_error))
            tg.start_soon(anyio.sleep, 999)  # Will be cancelled
    except BaseExceptionGroup as e:
        result = unwrap_task_group_exception(e)
        assert isinstance(result, ConnectionError)
        assert str(result) == "connection failed"


async def test_unwrap_exception_group_all_cancelled():
    """Test that when all exceptions are cancelled, the group is re-raised."""
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(anyio.sleep, 999)
            tg.cancel_scope.cancel()
    except BaseExceptionGroup as e:
        # Should return the group if all are cancelled
        result = unwrap_task_group_exception(e)
        assert isinstance(result, BaseExceptionGroup)


async def test_unwrap_preserves_non_cancelled_errors():
    """Test that all non-cancelled exceptions are preserved."""
    error1 = ValueError("error 1")
    error2 = RuntimeError("error 2")

    # Create an exception group with multiple real errors
    group = BaseExceptionGroup("multiple", [error1, error2])

    result = unwrap_task_group_exception(group)
    # Should return the first non-cancelled error
    assert result is error1
```

**Step 2: Run test to verify it fails**

```bash
uv run --frozen pytest tests/shared/test_exceptions.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp.shared.exceptions'` or `AttributeError: function 'unwrap_task_group_exception' not found`

**Step 3: Implement the unwrapping utility**

Add to file: `src/mcp/shared/exceptions.py` (at the end)

```python
def unwrap_task_group_exception(exc: BaseException) -> BaseException:
    """Unwrap an exception from a task group, extracting only the real error.

    When anyio task groups fail, they raise BaseExceptionGroup containing:
    - The original error that caused the failure
    - CancelledError from sibling tasks that were cancelled

    This function extracts only the real error, ignoring cancelled siblings.

    Args:
        exc: The exception to unwrap (could be any exception)

    Returns:
        The unwrapped exception if it was an ExceptionGroup with a real error,
        otherwise the original exception

    Example:
        ```python
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(task1)
                tg.start_soon(task2)
        except BaseExceptionGroup as e:
            # Extract only the real error, ignore CancelledError
            real_exc = unwrap_task_group_exception(e)
            raise real_exc
        ```
    """
    import anyio

    # If not an exception group, return as-is
    if not isinstance(exc, BaseExceptionGroup):
        return exc

    # Find the first non-cancelled exception
    cancelled_exc_class = anyio.get_cancelled_exc_class()
    for sub_exc in exc.exceptions:
        if not isinstance(sub_exc, cancelled_exc_class):
            return sub_exc

    # All were cancelled, return the group
    return exc
```

**Step 4: Run test to verify it passes**

```bash
uv run --frozen pytest tests/shared/test_exceptions.py -v
```

Expected: All tests PASS

**Step 5: Commit**

```bash
git add tests/shared/test_exceptions.py src/mcp/shared/exceptions.py
git commit -m "feat: add exception group unwrapping utility

ROOT CAUSE:
Task groups wrap real errors with CancelledError from siblings,
making error handling difficult for callers.

CHANGES:
- Added unwrap_task_group_exception() utility function
- Extracts real error from ExceptionGroup, ignores cancelled siblings

IMPACT:
- Enables clean error handling for SDK users

FILES MODIFIED:
- src/mcp/shared/exceptions.py: Added unwrap_task_group_exception()
- tests/shared/test_exceptions.py: Added tests for unwrapping behavior"
```

---

## Task 2: Fix BaseSession in shared/session.py

**Files:**
- Modify: `src/mcp/shared/session.py:214-231` (the `__aenter__` and `__aexit__` methods)

**Step 1: Write failing test demonstrating ExceptionGroup wrapping**

Create file: `tests/shared/test_session_exception_group.py`

```python
"""Test that BaseSession unwraps ExceptionGroups properly."""
from __future__ import annotations

import anyio
import pytest

from mcp.shared.session import BaseSession


class TestSession(BaseSession):
    """Test implementation of BaseSession."""

    @property
    def _receive_request_adapter(self):
        from pydantic import TypeAdapter
        return TypeAdapter(dict)

    @property
    def _receive_notification_adapter(self):
        from pydantic import TypeAdapter
        return TypeAdapter(dict)


async def test_session_propagates_real_error_not_exception_group():
    """Test that real errors propagate unwrapped from session task groups."""
    from mcp.types import JSONRPCNotification

    # Create streams
    read_stream_writer, read_stream = anyio.create_memory_object_stream()
    write_stream, write_stream_reader = anyio.create_memory_object_stream()

    # Create a task that will fail
    async def failing_task():
        await write_stream_writer.send(
            JSONRPCNotification(jsonrpc="2.0", method="test", params={})
        )
        raise ConnectionError("connection failed")

    try:
        session = TestSession(
            read_stream=read_stream,
            write_stream=write_stream,
            read_timeout_seconds=None,
        )

        # The session's receive loop will start in __aenter__
        # If it fails with ExceptionGroup, we want only the real error
        with pytest.raises(ConnectionError, match="connection failed"):
            async with session:
                # Send a notification to trigger the receive loop
                await failing_task()

    finally:
        await read_stream_writer.aclose()
        await read_stream.aclose()
        await write_stream.aclose()
        await write_stream_reader.aclose()
```

**Step 2: Run test to verify it fails (currently gets ExceptionGroup)**

```bash
uv run --frozen pytest tests/shared/test_session_exception_group.py -v
```

Expected: `Failed: DID NOT RAISE <class 'ConnectionError'>` or raises `BaseExceptionGroup` instead

**Step 3: Modify BaseSession to unwrap exceptions**

Modify: `src/mcp/shared/session.py` (lines 220-231)

Replace the `__aexit__` method:

```python
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> bool | None:
        from mcp.shared.exceptions import unwrap_task_group_exception

        await self._exit_stack.aclose()
        # Using BaseSession as a context manager should not block on exit (this
        # would be very surprising behavior), so make sure to cancel the tasks
        # in the task group.
        self._task_group.cancel_scope.cancel()

        # Exit the task group and unwrap any ExceptionGroup
        result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

        # If exiting raised an exception, unwrap it
        if exc_val is not None:
            # Unwrap ExceptionGroup to get only the real error
            unwrapped = unwrap_task_group_exception(exc_val)
            if unwrapped is not exc_val:
                # Re-raise the unwrapped exception
                raise unwrapped

        return result
```

**Step 4: Run test to verify it passes**

```bash
uv run --frozen pytest tests/shared/test_session_exception_group.py -v
```

Expected: Test PASSES (ConnectionError is raised directly, not wrapped)

**Step 5: Commit**

```bash
git add tests/shared/test_session_exception_group.py src/mcp/shared/session.py
git commit -m "fix(session): unwrap ExceptionGroup in BaseSession.__aexit__

ROOT CAUSE:
BaseSession's task group raises ExceptionGroup wrapping real errors
with CancelledError from cancelled tasks.

CHANGES:
- Modified __aexit__ to unwrap ExceptionGroup before propagating
- Real errors now propagate cleanly to callers

IMPACT:
- Callers can catch specific exceptions directly

FILES MODIFIED:
- src/mcp/shared/session.py: Added exception unwrapping in __aexit__
- tests/shared/test_session_exception_group.py: Added test"
```

---

## Task 3: Fix Client Transport Implementations

**Files:**
- Modify: `src/mcp/client/streamable_http.py:549-580` (streamable_http_client function)
- Modify: `src/mcp/client/websocket.py:71-75` (websocket_client function)
- Modify: `src/mcp/client/sse.py:63-85` (sse_client function)
- Modify: `src/mcp/client/stdio.py:180-195` (stdio_client function)

**Step 1: Write failing test for streamable_http_client**

Create file: `tests/client/test_streamable_http_exception_group.py`

```python
"""Test that streamable_http_client unwraps ExceptionGroups."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

import anyio


async def test_streamable_http_client_unwraps_exception_groups():
    """Test that real errors propagate unwrapped from streamable_http_client."""
    from mcp.client.streamable_http import streamable_http_client

    # Mock a failing HTTP connection
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client_class.return_value = mock_client

        # Mock the SSE connection to fail
        async def failing_sse():
            raise ConnectionError("SSE connection failed")

        with patch("mcp.client.streamable_http.aconnect_sse", side_effect=failing_sse):
            # Should raise ConnectionError, not BaseExceptionGroup
            with pytest.raises(ConnectionError, match="SSE connection failed"):
                async with streamable_http_client("http://localhost:8000"):
                    pass
```

**Step 2: Run test to verify it fails**

```bash
uv run --frozen pytest tests/client/test_streamable_http_exception_group.py -v
```

Expected: Raises `BaseExceptionGroup` instead of `ConnectionError`

**Step 3: Modify streamable_http_client to unwrap exceptions**

Modify: `src/mcp/client/streamable_http.py` (lines 549-580)

Wrap the task group to unwrap exceptions:

```python
    async with anyio.create_task_group() as tg:
        try:
            logger.debug(f"Connecting to StreamableHTTP endpoint: {url}")

            async with contextlib.AsyncExitStack() as stack:
                # Only manage client lifecycle if we created it
                if not client_provided:
                    await stack.enter_async_context(client)

                def start_get_stream() -> None:
                    tg.start_soon(transport.handle_get_stream, client, read_stream_writer)

                tg.start_soon(
                    transport.post_writer,
                    client,
                    write_stream_reader,
                    read_stream_writer,
                    write_stream,
                    start_get_stream,
                    tg,
                )

                try:
                    yield read_stream, write_stream
                finally:
                    if transport.session_id and terminate_on_close:
                        await transport.terminate_session(client)
                    tg.cancel_scope.cancel()
        except BaseExceptionGroup as e:
            # Unwrap ExceptionGroup to get only the real error
            from mcp.shared.exceptions import unwrap_task_group_exception

            real_exc = unwrap_task_group_exception(e)
            if real_exc is not e:
                raise real_exc
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
```

**Step 4: Run test to verify it passes**

```bash
uv run --frozen pytest tests/client/test_streamable_http_exception_group.py -v
```

Expected: Test PASSES

**Step 5: Apply same pattern to websocket_client**

Modify: `src/mcp/client/websocket.py` (around line 71)

Add exception unwrapping:

```python
        async with anyio.create_task_group() as tg:
            try:
                # Start reader and writer tasks
                tg.start_soon(ws_reader)
                tg.start_soon(ws_writer)

                yield (read_stream, write_stream)
            except BaseExceptionGroup as e:
                from mcp.shared.exceptions import unwrap_task_group_exception

                real_exc = unwrap_task_group_exception(e)
                if real_exc is not e:
                    raise real_exc
```

**Step 6: Apply same pattern to sse_client**

Modify: `src/mcp/client/sse.py` (around line 63)

Add exception unwrapping:

```python
    async with anyio.create_task_group() as tg:
        try:
            logger.debug(f"Connecting to SSE endpoint: {remove_request_params(url)}")
            async with httpx_client_factory(
                timeout=client_timeout
            ) as httpx_client:
                # Start reader task
                tg.start_soon(
                    sse_reader, httpx_client, read_stream_writer, request_counter
                )

                # Enter the streams context
                async with write_stream_reader, write_stream:
                    yield (read_stream, write_stream)
        except BaseExceptionGroup as e:
            from mcp.shared.exceptions import unwrap_task_group_exception

            real_exc = unwrap_task_group_exception(e)
            if real_exc is not e:
                raise real_exc
```

**Step 7: Apply same pattern to stdio_client**

Modify: `src/mcp/client/stdio.py` (around line 180)

Add exception unwrapping:

```python
    async with anyio.create_task_group() as tg, process:
        try:
            tg.start_soon(stdout_reader)
            tg.start_soon(stdin_writer)
            try:
                yield (read_stream, write_stream)
            finally:
                tg.cancel_scope.cancel()
        except BaseExceptionGroup as e:
            from mcp.shared.exceptions import unwrap_task_group_exception

            real_exc = unwrap_task_group_exception(e)
            if real_exc is not e:
                raise real_exc
```

**Step 8: Commit**

```bash
git add tests/client/test_streamable_http_exception_group.py
git add src/mcp/client/streamable_http.py src/mcp/client/websocket.py
git add src/mcp/client/sse.py src/mcp/client/stdio.py
git commit -m "fix(client): unwrap ExceptionGroup in transport clients

ROOT CAUSE:
Transport clients propagate ExceptionGroup wrapping real errors.

CHANGES:
- Added exception unwrapping in streamable_http_client
- Added exception unwrapping in websocket_client
- Added exception unwrapping in sse_client
- Added exception unwrapping in stdio_client

IMPACT:
- Callers can catch specific exceptions directly

FILES MODIFIED:
- src/mcp/client/streamable_http.py
- src/mcp/client/websocket.py
- src/mcp/client/sse.py
- src/mcp/client/stdio.py
- tests/client/test_streamable_http_exception_group.py"
```

---

## Task 4: Fix Server Transport Implementations

**Files:**
- Modify: `src/mcp/server/sse.py:177-220` (sse_server function)
- Modify: `src/mcp/server/stdio.py:80-95` (stdio_server function)
- Modify: `src/mcp/server/websocket.py:55-70` (websocket_server function)
- Modify: `src/mcp/server/streamable_http.py:617-650, 973-1010` (streamable_http_server)

**Step 1: Write failing test for stdio_server**

Create file: `tests/server/test_stdio_exception_group.py`

```python
"""Test that server transports unwrap ExceptionGroups."""
from __future__ import annotations

import pytest

import anyio


async def test_stdio_server_unwraps_exception_groups():
    """Test that real errors propagate unwrapped from stdio_server."""
    from mcp.server.stdio import stdio_server

    async def failing_handler():
        raise ValueError("handler failed")

    # Should raise ValueError, not BaseExceptionGroup
    with pytest.raises(ValueError, match="handler failed"):
        async with stdio_server() as (read_stream, write_stream):
            # Trigger the error
            async with anyio.create_task_group() as tg:
                tg.start_soon(failing_handler)
```

**Step 2: Run test to verify it fails**

```bash
uv run --frozen pytest tests/server/test_stdio_exception_group.py -v
```

**Step 3: Apply exception unwrapping to all server transports**

Modify each server transport similarly:

For `src/mcp/server/sse.py` (around line 177):
```python
        async with anyio.create_task_group() as tg:

            async def response_wrapper(scope: Scope, receive: Receive, send: Send):
                """The EventSourceResponse returning signals a client close / disconnect."""
                # ... existing code ...

            try:
                # ... existing task group code ...
            except BaseExceptionGroup as e:
                from mcp.shared.exceptions import unwrap_task_group_exception

                real_exc = unwrap_task_group_exception(e)
                if real_exc is not e:
                    raise real_exc
```

For `src/mcp/server/stdio.py` (around line 80):
```python
    async with anyio.create_task_group() as tg:
        try:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
        except BaseExceptionGroup as e:
            from mcp.shared.exceptions import unwrap_task_group_exception

            real_exc = unwrap_task_group_exception(e)
            if real_exc is not e:
                raise real_exc
```

For `src/mcp/server/websocket.py` (around line 55):
```python
    async with anyio.create_task_group() as tg:
        try:
            tg.start_soon(ws_reader)
            tg.start_soon(ws_writer)
            yield (read_stream, write_stream)
        except BaseExceptionGroup as e:
            from mcp.shared.exceptions import unwrap_task_group_exception

            real_exc = unwrap_task_group_exception(e)
            if real_exc is not e:
                raise real_exc
```

For `src/mcp/server/streamable_http.py`:
- Around line 617 (first task group)
- Around line 973 (second task group)

Apply same pattern to both locations.

**Step 4: Run tests to verify they pass**

```bash
uv run --frozen pytest tests/server/test_stdio_exception_group.py -v
```

**Step 5: Commit**

```bash
git add tests/server/test_stdio_exception_group.py
git add src/mcp/server/sse.py src/mcp/server/stdio.py
git add src/mcp/server/websocket.py src/mcp/server/streamable_http.py
git commit -m "fix(server): unwrap ExceptionGroup in transport servers

ROOT CAUSE:
Server transports propagate ExceptionGroup wrapping real errors.

CHANGES:
- Added exception unwrapping in sse_server
- Added exception unwrapping in stdio_server
- Added exception unwrapping in websocket_server
- Added exception unwrapping in streamable_http_server (2 locations)

IMPACT:
- Callers can catch specific exceptions directly

FILES MODIFIED:
- src/mcp/server/sse.py
- src/mcp/server/stdio.py
- src/mcp/server/websocket.py
- src/mcp/server/streamable_http.py
- tests/server/test_stdio_exception_group.py"
```

---

## Task 5: Fix Remaining Task Group Usages

**Files:**
- Modify: `src/mcp/server/streamable_http_manager.py:125-140`
- Modify: `src/mcp/server/lowlevel/server.py:392-410`
- Modify: `src/mcp/server/experimental/task_support.py:82-100`
- Modify: `src/mcp/server/experimental/task_result_handler.py:165-200`
- Modify: `src/mcp/client/session_group.py:169-175`
- Modify: `src/mcp/client/_memory.py:51-70`

**Step 1: Apply exception unwrapping to streamable_http_manager**

Modify: `src/mcp/server/streamable_http_manager.py` (lines 125-140)

```python
        async with anyio.create_task_group() as tg:
            try:
                # Store the task group for later use
                self._task_group = tg
                logger.info("StreamableHTTP session manager started")

                # ... existing code ...

            except BaseExceptionGroup as e:
                from mcp.shared.exceptions import unwrap_task_group_exception

                real_exc = unwrap_task_group_exception(e)
                if real_exc is not e:
                    raise real_exc
```

**Step 2: Apply exception unwrapping to lowlevel/server**

Modify: `src/mcp/server/lowlevel/server.py` (lines 392-410)

```python
            async with anyio.create_task_group() as tg:
                try:
                    async for message in session.incoming_messages:
                        logger.debug("Received message: %s", message)

                        # ... existing message handling ...

                except BaseExceptionGroup as e:
                    from mcp.shared.exceptions import unwrap_task_group_exception

                    real_exc = unwrap_task_group_exception(e)
                    if real_exc is not e:
                        raise real_exc
```

**Step 3: Apply exception unwrapping to experimental task_support**

Modify: `src/mcp/server/experimental/task_support.py` (lines 82-100)

```python
        async with anyio.create_task_group() as tg:
            try:
                self._task_group = tg
                yield
            except BaseExceptionGroup as e:
                from mcp.shared.exceptions import unwrap_task_group_exception

                real_exc = unwrap_task_group_exception(e)
                if real_exc is not e:
                    raise real_exc
```

**Step 4: Apply exception unwrapping to task_result_handler**

Modify: `src/mcp/server/experimental/task_result_handler.py` (lines 165-200)

```python
        async with anyio.create_task_group() as tg:

            async def wait_for_store() -> None:
                # ... existing code ...

            async def wait_for_queue_message() -> None:
                # ... existing code ...

            try:
                tg.start_soon(wait_for_store)
                tg.start_soon(wait_for_queue_message)
            except BaseExceptionGroup as e:
                from mcp.shared.exceptions import unwrap_task_group_exception

                real_exc = unwrap_task_group_exception(e)
                if real_exc is not e:
                    raise real_exc
```

**Step 5: Apply exception unwrapping to session_group**

Modify: `src/mcp/client/session_group.py` (lines 169-175)

```python
        async with anyio.create_task_group() as tg:
            try:
                for exit_stack in self._session_exit_stacks.values():
                    tg.start_soon(exit_stack.aclose)
            except BaseExceptionGroup as e:
                from mcp.shared.exceptions import unwrap_task_group_exception

                real_exc = unwrap_task_group_exception(e)
                if real_exc is not e:
                    raise real_exc
```

**Step 6: Apply exception unwrapping to _memory transport**

Modify: `src/mcp/client/_memory.py` (lines 51-70)

```python
            async with anyio.create_task_group() as tg:
                try:
                    # Start server in background
                    tg.start_soon(
                        lambda: actual_server.run(
                            client_read, client_write
                        )
                    )

                    # Yield the streams
                    yield client_streams
                except BaseExceptionGroup as e:
                    from mcp.shared.exceptions import unwrap_task_group_exception

                    real_exc = unwrap_task_group_exception(e)
                    if real_exc is not e:
                        raise real_exc
```

**Step 7: Run all tests to verify**

```bash
uv run --frozen pytest -xvs
```

**Step 8: Commit**

```bash
git add src/mcp/server/streamable_http_manager.py
git add src/mcp/server/lowlevel/server.py
git add src/mcp/server/experimental/task_support.py
git add src/mcp/server/experimental/task_result_handler.py
git add src/mcp/client/session_group.py
git add src/mcp/client/_memory.py
git commit -m "fix(remaining): unwrap ExceptionGroup in remaining task groups

ROOT CAUSE:
Remaining task group usages propagate ExceptionGroup.

CHANGES:
- Added exception unwrapping in StreamableHTTPManager
- Added exception unwrapping in lowlevel server
- Added exception unwrapping in experimental task support
- Added exception unwrapping in task result handler
- Added exception unwrapping in session group
- Added exception unwrapping in memory transport

IMPACT:
- All task groups now properly unwrap ExceptionGroups

FILES MODIFIED:
- src/mcp/server/streamable_http_manager.py
- src/mcp/server/lowlevel/server.py
- src/mcp/server/experimental/task_support.py
- src/mcp/server/experimental/task_result_handler.py
- src/mcp/client/session_group.py
- src/mcp/client/_memory.py"
```

---

## Task 6: Verify All Tests Pass and Coverage

**Step 1: Run full test suite**

```bash
uv run --frozen pytest -xvs
```

Expected: All tests PASS

**Step 2: Check coverage on modified files**

```bash
uv run --frozen pytest --cov=src/mcp/shared/exceptions --cov=src/mcp/shared/session --cov-report=term-missing
```

Expected: 100% branch coverage on new code

**Step 3: Run type checking**

```bash
uv run --frozen pyright
```

Expected: No type errors

**Step 4: Run linting**

```bash
uv run --frozen ruff check .
uv run --frozen ruff format .
```

Expected: No lint errors, code properly formatted

**Step 5: Final commit if needed**

If any fixes were needed:

```bash
git add .
git commit -m "chore: fix test/coverage/lint issues from ExceptionGroup unwrapping"
```

---

## Task 7: Update Documentation

**Step 1: Check if migration guide needs update**

Read: `docs/migration.md`

If there are breaking changes or behavior changes, add an entry.

**Step 2: Commit any documentation updates**

```bash
git add docs/
git commit -m "docs: document ExceptionGroup unwrapping behavior"
```

---

## Summary

This plan addresses issue #2114 by:

1. Creating a reusable `unwrap_task_group_exception()` utility
2. Wrapping all 16 `create_task_group()` usages to unwrap ExceptionGroups
3. Adding tests to verify the behavior
4. Ensuring callers receive clean, catchable exceptions

**Total files modified:** ~19 files
**New test files:** 3 files
**Tasks:** 7 bite-sized tasks

---

**For Implementer:** This plan is designed to be executed task-by-task. After each task, run the tests to verify before proceeding. Use the @superpowers:executing-plans skill for systematic execution.
