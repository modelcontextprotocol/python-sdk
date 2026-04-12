"""Tests for mcp.server.mcpserver.utilities.roots."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.server.mcpserver.utilities.roots import (
    assert_within_roots,
    get_roots,
    within_roots_check,
)

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx(root_uris: list[str]) -> MagicMock:
    root_objects = [MagicMock(uri=uri) for uri in root_uris]
    list_roots_result = MagicMock()
    list_roots_result.roots = root_objects
    session = MagicMock()
    session.list_roots = AsyncMock(return_value=list_roots_result)
    ctx = MagicMock()
    ctx.session = session
    return ctx


def make_failing_ctx() -> MagicMock:
    session = MagicMock()
    session.list_roots = AsyncMock(side_effect=Exception("not supported"))
    ctx = MagicMock()
    ctx.session = session
    return ctx


# ---------------------------------------------------------------------------
# get_roots
# ---------------------------------------------------------------------------


async def test_get_roots_returns_uris():
    ctx = make_ctx(["file:///home/user/project", "file:///tmp/work"])
    result = await get_roots(ctx)
    assert result == ["file:///home/user/project", "file:///tmp/work"]


async def test_get_roots_returns_empty_when_no_roots():
    ctx = make_ctx([])
    result = await get_roots(ctx)
    assert result == []


async def test_get_roots_returns_empty_on_exception():
    ctx = make_failing_ctx()
    result = await get_roots(ctx)
    assert result == []


# ---------------------------------------------------------------------------
# assert_within_roots
# ---------------------------------------------------------------------------


async def test_assert_passes_when_no_roots():
    ctx = make_ctx([])
    await assert_within_roots("/any/path/at/all", ctx)


async def test_assert_passes_when_path_inside_root():
    ctx = make_ctx(["file:///home/user/project"])
    await assert_within_roots("/home/user/project/src/main.py", ctx)


async def test_assert_raises_when_path_outside_root():
    ctx = make_ctx(["file:///home/user/project"])
    with pytest.raises(PermissionError, match="Access denied"):
        await assert_within_roots("/etc/passwd", ctx)


async def test_assert_passes_with_multiple_roots_matching_second():
    ctx = make_ctx(["file:///home/user/project", "file:///tmp/work"])
    await assert_within_roots("/tmp/work/file.txt", ctx)


async def test_assert_raises_outside_all_roots():
    ctx = make_ctx(["file:///home/user/project", "file:///tmp/work"])
    with pytest.raises(PermissionError):
        await assert_within_roots("/var/log/syslog", ctx)


async def test_assert_accepts_pathlib_path():
    ctx = make_ctx(["file:///home/user/project"])
    await assert_within_roots(Path("/home/user/project/file.txt"), ctx)


async def test_assert_skips_non_file_roots():
    ctx = make_ctx(["https://api.example.com/v1"])
    await assert_within_roots("/any/local/path", ctx)


async def test_assert_no_raise_when_client_doesnt_support_roots():
    ctx = make_failing_ctx()
    await assert_within_roots("/any/path", ctx)


# ---------------------------------------------------------------------------
# within_roots_check decorator
# ---------------------------------------------------------------------------


async def test_decorator_passes_inside_root():
    ctx = make_ctx(["file:///home/user/project"])

    @within_roots_check
    async def read_file(path: str, ctx: MagicMock) -> str:
        return "file contents"

    result = await read_file(path="/home/user/project/notes.txt", ctx=ctx)
    assert result == "file contents"


async def test_decorator_raises_outside_root():
    ctx = make_ctx(["file:///home/user/project"])

    @within_roots_check
    async def read_file(path: str, ctx: MagicMock) -> str:
        raise AssertionError("tool body must not run when decorator denies access")  # pragma: no cover

    with pytest.raises(PermissionError):
        await read_file(path="/etc/passwd", ctx=ctx)


async def test_decorator_checks_star_path_params():
    ctx = make_ctx(["file:///home/user/project"])

    @within_roots_check
    async def copy_file(source_path: str, dest_path: str, ctx: MagicMock) -> str:
        raise AssertionError("tool body must not run when decorator denies access")  # pragma: no cover

    with pytest.raises(PermissionError):
        await copy_file(
            source_path="/home/user/project/file.txt",
            dest_path="/etc/shadow",
            ctx=ctx,
        )


async def test_decorator_ignores_non_path_string_params():
    ctx = make_ctx(["file:///home/user/project"])

    @within_roots_check
    async def tool(name: str, path: str, ctx: MagicMock) -> str:
        return f"{name}:{path}"

    result = await tool(
        name="greeting",
        path="/home/user/project/file.txt",
        ctx=ctx,
    )
    assert result == "greeting:/home/user/project/file.txt"


async def test_decorator_raises_without_ctx():
    @within_roots_check
    async def bad_tool(path: str) -> str:
        raise AssertionError("tool body must not run when ctx is missing")  # pragma: no cover

    with pytest.raises(ValueError, match="ctx"):
        await bad_tool(path="/some/path")
