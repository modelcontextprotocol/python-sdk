"""Tests for mcp.shared._task_group — collapsing ExceptionGroup wrapper."""

import sys

import anyio
import pytest
from anyio.abc import TaskStatus

from mcp.shared._task_group import (
    _CollapsingTaskGroup,
    collapse_exception_group,
    create_mcp_task_group,
)

if sys.version_info < (3, 11):  # pragma: lax no cover
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup  # pragma: lax no cover

# ---------------------------------------------------------------------------
# collapse_exception_group unit tests
# ---------------------------------------------------------------------------


def test_collapse_single_exception() -> None:
    """A group containing one exception is unwrapped."""
    inner = ConnectionError("boom")
    group = ExceptionGroup("g", [inner])
    assert collapse_exception_group(group) is inner


def test_collapse_nested_single() -> None:
    """Recursively unwraps nested single-exception groups."""
    inner = ValueError("deep")
    group = ExceptionGroup("outer", [ExceptionGroup("inner", [inner])])
    assert collapse_exception_group(group) is inner


def test_collapse_multiple_exceptions_unchanged() -> None:
    """Groups with >1 exception are returned unchanged."""
    exc_a = TypeError("a")
    exc_b = RuntimeError("b")
    group = ExceptionGroup("g", [exc_a, exc_b])
    assert collapse_exception_group(group) is group


def test_collapse_base_exception_group() -> None:
    """Works with BaseExceptionGroup (e.g. containing KeyboardInterrupt)."""
    inner = KeyboardInterrupt()
    group = BaseExceptionGroup("g", [inner])
    assert collapse_exception_group(group) is inner


# ---------------------------------------------------------------------------
# _CollapsingTaskGroup integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_task_failure_is_unwrapped() -> None:
    """A single failing task raises its exception directly, not wrapped."""
    with pytest.raises(ConnectionError, match="server down"):
        async with create_mcp_task_group() as tg:

            async def failing() -> None:
                raise ConnectionError("server down")

            tg.start_soon(failing)


@pytest.mark.anyio
async def test_single_task_failure_with_cancelled_sibling() -> None:
    """When one task fails and another is cancelled, the real error surfaces."""
    with pytest.raises(ConnectionError, match="oops"):
        async with create_mcp_task_group() as tg:

            async def failing() -> None:
                raise ConnectionError("oops")

            async def long_running() -> None:
                await anyio.sleep(999)

            tg.start_soon(failing)
            tg.start_soon(long_running)


@pytest.mark.anyio
async def test_multiple_failures_stay_grouped() -> None:
    """When multiple tasks fail, an ExceptionGroup is raised."""
    with pytest.raises(BaseExceptionGroup):
        async with create_mcp_task_group() as tg:
            ready = anyio.Event()

            async def fail_a() -> None:
                await ready.wait()
                raise ConnectionError("a")

            async def fail_b() -> None:
                ready.set()
                raise ValueError("b")

            tg.start_soon(fail_a)
            tg.start_soon(fail_b)


@pytest.mark.anyio
async def test_no_failure_passes_cleanly() -> None:
    """Normal execution does not raise."""
    results: list[int] = []
    async with create_mcp_task_group() as tg:

        async def worker(n: int) -> None:
            results.append(n)

        tg.start_soon(worker, 1)
        tg.start_soon(worker, 2)

    assert sorted(results) == [1, 2]


@pytest.mark.anyio
async def test_cancel_scope_is_delegated() -> None:
    """cancel_scope is accessible and works."""
    async with create_mcp_task_group() as tg:
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_start_delegates_to_task_group() -> None:
    """start() delegates to the underlying task group."""

    async def task_with_status(*, task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED) -> None:
        task_status.started("ready")
        await anyio.sleep(999)

    async with create_mcp_task_group() as tg:
        result = await tg.start(task_with_status)
        assert result == "ready"
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_task_group_not_entered_raises() -> None:
    """Accessing methods before __aenter__ raises RuntimeError."""
    ctg = _CollapsingTaskGroup()
    with pytest.raises(RuntimeError, match="not been entered"):
        ctg.cancel_scope
    with pytest.raises(RuntimeError, match="not been entered"):
        ctg.start_soon(lambda: None)


@pytest.mark.anyio
async def test_collapsed_exception_preserves_cause_chain() -> None:
    """The collapsed exception has the original ExceptionGroup as __cause__."""
    with pytest.raises(RuntimeError, match="root cause") as exc_info:
        async with create_mcp_task_group() as tg:

            async def failing() -> None:
                raise RuntimeError("root cause")

            tg.start_soon(failing)

    assert isinstance(exc_info.value.__cause__, BaseExceptionGroup)


@pytest.mark.anyio
async def test_start_failure_is_unwrapped() -> None:
    """An exception from start() is also unwrapped."""

    async def fail_on_start(*, task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED) -> None:
        raise ConnectionError("startup failed")

    with pytest.raises(ConnectionError, match="startup failed"):
        async with create_mcp_task_group() as tg:
            await tg.start(fail_on_start)


# ---------------------------------------------------------------------------
# Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/2114
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_issue_2114_except_specific_error_type() -> None:
    """Callers can catch specific exception types without ExceptionGroup wrapping.

    Before the fix, anyio task groups always wrapped exceptions in
    ExceptionGroup, making ``except ConnectionError:`` impossible.
    """
    caught: BaseException | None = None
    try:
        async with create_mcp_task_group() as tg:

            async def background() -> None:
                await anyio.sleep(999)

            async def connect() -> None:
                raise ConnectionError("connection refused")

            tg.start_soon(background)
            tg.start_soon(connect)

    except ConnectionError as exc:
        caught = exc

    assert caught is not None
    assert str(caught) == "connection refused"
    assert isinstance(caught.__cause__, BaseExceptionGroup)
