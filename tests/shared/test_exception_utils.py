"""Tests for mcp.shared._exception_utils — ExceptionGroup collapsing."""

from __future__ import annotations

import asyncio
import sys

import anyio
import pytest

from mcp.shared._exception_utils import collapse_exception_group, open_task_group

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup


# ---------------------------------------------------------------------------
# collapse_exception_group() unit tests
# ---------------------------------------------------------------------------


class TestCollapseExceptionGroup:
    """Unit tests for the pure-function collapser."""

    def test_single_real_error_with_cancelled_siblings(self) -> None:
        """One real error + N Cancelled → unwrap to the real error."""
        real = ConnectionError("lost connection")
        eg = BaseExceptionGroup(
            "task group",
            [real, asyncio.CancelledError(), asyncio.CancelledError()],
        )
        result = collapse_exception_group(eg)
        assert result is real

    def test_all_cancelled(self) -> None:
        """Only Cancelled exceptions → return a single Cancelled."""
        c1 = asyncio.CancelledError()
        c2 = asyncio.CancelledError()
        eg = BaseExceptionGroup("task group", [c1, c2])
        result = collapse_exception_group(eg)
        assert isinstance(result, asyncio.CancelledError)

    def test_multiple_real_errors(self) -> None:
        """Multiple non-Cancelled errors → return filtered group (no Cancelled)."""
        e1 = ValueError("bad value")
        e2 = RuntimeError("runtime issue")
        eg = BaseExceptionGroup(
            "task group",
            [e1, asyncio.CancelledError(), e2],
        )
        result = collapse_exception_group(eg)
        assert isinstance(result, BaseExceptionGroup)
        # Should contain only the two real errors
        assert len(result.exceptions) == 2
        assert e1 in result.exceptions
        assert e2 in result.exceptions

    def test_single_real_error_no_cancelled(self) -> None:
        """One real error, no Cancelled → unwrap to the real error."""
        real = TypeError("wrong type")
        eg = BaseExceptionGroup("task group", [real])
        result = collapse_exception_group(eg)
        assert result is real

    def test_multiple_real_errors_no_cancelled(self) -> None:
        """Multiple real errors, no Cancelled → return group with same exceptions."""
        e1 = ValueError("a")
        e2 = ValueError("b")
        eg = BaseExceptionGroup("task group", [e1, e2])
        result = collapse_exception_group(eg)
        assert isinstance(result, BaseExceptionGroup)
        assert len(result.exceptions) == 2
        assert e1 in result.exceptions
        assert e2 in result.exceptions


# ---------------------------------------------------------------------------
# open_task_group() integration tests
# ---------------------------------------------------------------------------


class TestOpenTaskGroup:
    """Integration tests for the context manager."""

    @pytest.mark.anyio
    async def test_single_task_failure_unwrapped(self) -> None:
        """A single failing task should raise its error directly, not wrapped."""
        with pytest.raises(ConnectionError, match="server gone"):
            async with open_task_group() as tg:
                tg.start_soon(self._fail_with, ConnectionError("server gone"))
                # Keep the group alive so the failure propagates
                await anyio.sleep_forever()

    @pytest.mark.anyio
    async def test_no_failure_no_exception(self) -> None:
        """Normal exit — no exception raised."""
        async with open_task_group() as tg:
            tg.start_soon(anyio.sleep, 0)

    @pytest.mark.anyio
    async def test_multiple_failures_preserved(self) -> None:
        """Multiple concurrent failures should still raise BaseExceptionGroup."""
        with pytest.raises(BaseExceptionGroup) as exc_info:
            async with open_task_group() as tg:
                tg.start_soon(self._fail_with, ValueError("a"))
                tg.start_soon(self._fail_with, RuntimeError("b"))
                await anyio.sleep_forever()

        # The group should contain both real errors
        eg = exc_info.value
        types = {type(e) for e in eg.exceptions}
        assert ValueError in types
        assert RuntimeError in types

    @pytest.mark.anyio
    async def test_cause_chain_preserved(self) -> None:
        """The original BaseExceptionGroup should be attached as __cause__."""
        with pytest.raises(ConnectionError) as exc_info:
            async with open_task_group() as tg:
                tg.start_soon(self._fail_with, ConnectionError("oops"))
                await anyio.sleep_forever()

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, BaseExceptionGroup)

    @staticmethod
    async def _fail_with(exc: BaseException) -> None:
        raise exc
