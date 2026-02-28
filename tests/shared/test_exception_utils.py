"""Tests for exception group collapsing utilities."""

import sys

import pytest

import anyio

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

from mcp.shared._exception_utils import collapse_exception_group, create_task_group


class TestCollapseExceptionGroup:
    """Tests for the collapse_exception_group function."""

    @pytest.mark.anyio
    async def test_single_real_error_with_cancelled(self) -> None:
        """A single real error alongside Cancelled exceptions should be extracted."""
        real_error = RuntimeError("connection failed")
        cancelled = anyio.get_cancelled_exc_class()()

        group = BaseExceptionGroup("test", [real_error, cancelled])
        result = collapse_exception_group(group)

        assert result is real_error

    @pytest.mark.anyio
    async def test_single_real_error_only(self) -> None:
        """A single real error without Cancelled should be extracted."""
        real_error = ValueError("bad value")

        group = BaseExceptionGroup("test", [real_error])
        result = collapse_exception_group(group)

        assert result is real_error

    @pytest.mark.anyio
    async def test_multiple_real_errors_preserved(self) -> None:
        """Multiple non-cancellation errors should keep the group intact."""
        err1 = RuntimeError("first")
        err2 = ValueError("second")

        group = BaseExceptionGroup("test", [err1, err2])
        result = collapse_exception_group(group)

        assert result is group

    @pytest.mark.anyio
    async def test_all_cancelled_preserved(self) -> None:
        """All-cancelled groups should be returned as-is."""
        cancelled_class = anyio.get_cancelled_exc_class()
        group = BaseExceptionGroup("test", [cancelled_class(), cancelled_class()])
        result = collapse_exception_group(group)

        assert result is group

    @pytest.mark.anyio
    async def test_multiple_cancelled_one_real(self) -> None:
        """One real error with multiple Cancelled should extract the real error."""
        cancelled_class = anyio.get_cancelled_exc_class()
        real_error = ConnectionError("lost connection")

        group = BaseExceptionGroup("test", [cancelled_class(), real_error, cancelled_class()])
        result = collapse_exception_group(group)

        assert result is real_error


class TestCreateTaskGroup:
    """Tests for the create_task_group context manager."""

    @pytest.mark.anyio
    async def test_single_failure_unwrapped(self) -> None:
        """A single task failure should propagate the original exception, not a group."""
        with pytest.raises(RuntimeError, match="task failed"):
            async with create_task_group() as tg:

                async def failing_task() -> None:
                    raise RuntimeError("task failed")

                async def long_task() -> None:
                    await anyio.sleep(100)

                tg.start_soon(failing_task)
                tg.start_soon(long_task)

    @pytest.mark.anyio
    async def test_no_failure_clean_exit(self) -> None:
        """Task group with no failures should exit cleanly."""
        results: list[int] = []
        async with create_task_group() as tg:

            async def worker(n: int) -> None:
                results.append(n)

            tg.start_soon(worker, 1)
            tg.start_soon(worker, 2)

        assert sorted(results) == [1, 2]

    @pytest.mark.anyio
    async def test_chained_cause(self) -> None:
        """The collapsed exception should chain to the original group via __cause__."""
        with pytest.raises(RuntimeError) as exc_info:
            async with create_task_group() as tg:

                async def failing_task() -> None:
                    raise RuntimeError("root cause")

                async def long_task() -> None:
                    await anyio.sleep(100)

                tg.start_soon(failing_task)
                tg.start_soon(long_task)

        assert isinstance(exc_info.value.__cause__, BaseExceptionGroup)
