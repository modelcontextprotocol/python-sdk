"""Reusable roots enforcement utilities for MCPServer.

Roots define filesystem boundaries that the MCP client declares to the server.
The MCP spec does not auto-enforce these — servers must do it themselves.
This module provides a simple reusable way to do that without rewriting
the logic in every server.

Usage:
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.server.mcpserver.utilities.roots import (
        get_roots,
        assert_within_roots,
        within_roots_check,
    )

    mcp = MCPServer("my-server")

    @mcp.tool()
    async def read_file(path: str, ctx: Context) -> str:
        await assert_within_roots(path, ctx)
        return open(path).read()
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

P = ParamSpec("P")
R = TypeVar("R")


async def get_roots(ctx: Context) -> list[str]:
    """Fetch the list of root URIs declared by the connected client.

    Returns a list of URI strings e.g. ["file:///home/user/project"].
    Returns an empty list if the client declared no roots or does not
    support the roots capability.

    Args:
        ctx: The MCPServer Context object available inside any tool.

    Example:
        @mcp.tool()
        async def my_tool(ctx: Context) -> str:
            roots = await get_roots(ctx)
            return str(roots)
    """
    try:
        result = await ctx.session.list_roots()
        return [str(root.uri) for root in result.roots]
    except Exception:
        return []


async def assert_within_roots(path: str | Path, ctx: Context) -> None:
    """Raise PermissionError if path falls outside all client-declared roots.

    If the client declared no roots this is a no-op — no restriction applied.
    Only file:// URIs are checked. Non-file roots are skipped.

    Args:
        path: The filesystem path your tool wants to access.
        ctx:  The MCPServer Context object available inside any tool.

    Raises:
        PermissionError: If the resolved path is outside all declared roots.

    Example:
        @mcp.tool()
        async def read_file(path: str, ctx: Context) -> str:
            await assert_within_roots(path, ctx)
            return open(path).read()
    """
    roots = await get_roots(ctx)

    if not roots:
        return

    file_roots = [str(Path(r.removeprefix("file://")).resolve()) for r in roots if r.startswith("file://")]

    if not file_roots:
        return

    resolved = str(Path(path).resolve())

    if not any(resolved.startswith(root) for root in file_roots):
        raise PermissionError(f"Access denied: '{resolved}' is outside the allowed roots.\nAllowed roots: {file_roots}")


def within_roots_check(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Auto-enforce roots on any tool parameter named 'path' or ending with '_path'.

    Requires the tool to also accept a `ctx: Context` parameter.

    Example:
        @mcp.tool()
        @within_roots_check
        async def read_file(path: str, ctx: Context) -> str:
            return open(path).read()
    """

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        sig = inspect.signature(fn)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = bound.arguments

        ctx = arguments.get("ctx")
        if ctx is None:
            raise ValueError("@within_roots_check requires the tool to have a `ctx: Context` parameter.")

        for param_name, value in arguments.items():
            if value and isinstance(value, str | Path):
                if param_name == "path" or param_name.endswith("_path"):
                    await assert_within_roots(value, ctx)

        return await fn(*args, **kwargs)

    return wrapper
