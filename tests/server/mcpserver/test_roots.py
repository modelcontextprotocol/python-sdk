from pathlib import Path

import pytest
from pydantic import FileUrl

from mcp import Client
from mcp.client.session import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared._context import RequestContext
from mcp.types import ListRootsResult, Root, TextContent


def _make_callback(roots: list[Root]):
    async def list_roots_callback(
        context: RequestContext[ClientSession],
    ) -> ListRootsResult:
        return ListRootsResult(roots=roots)

    return list_roots_callback


@pytest.mark.anyio
async def test_path_within_root_passes(tmp_path: Path):
    """A path inside a declared root should not raise."""
    inside = tmp_path / "file.txt"
    inside.touch()

    server = MCPServer("test")

    @server.tool("check")
    async def check(context: Context, path: str) -> bool:
        await context.assert_within_roots(path)
        return True

    callback = _make_callback([Root(uri=FileUrl(f"file://{tmp_path}"))])

    async with Client(server, list_roots_callback=callback) as client:
        result = await client.call_tool("check", {"path": str(inside)})
        assert result.is_error is False


@pytest.mark.anyio
async def test_path_outside_roots_raises(tmp_path: Path):
    """A path outside every declared root should raise PermissionError."""
    root_dir = tmp_path / "allowed"
    root_dir.mkdir()
    outside = tmp_path / "elsewhere.txt"
    outside.touch()

    server = MCPServer("test")

    @server.tool("check")
    async def check(context: Context, path: str) -> bool:
        await context.assert_within_roots(path)
        return True

    callback = _make_callback([Root(uri=FileUrl(f"file://{root_dir}"))])

    async with Client(server, list_roots_callback=callback) as client:
        result = await client.call_tool("check", {"path": str(outside)})
        assert result.is_error is True
        assert isinstance(result.content[0], TextContent)
        assert "not within any declared root" in result.content[0].text


@pytest.mark.anyio
async def test_no_roots_declared_raises(tmp_path: Path):
    """An empty roots list should always raise."""
    target = tmp_path / "file.txt"
    target.touch()

    server = MCPServer("test")

    @server.tool("check")
    async def check(context: Context, path: str) -> bool:
        await context.assert_within_roots(path)
        return True

    callback = _make_callback([])

    async with Client(server, list_roots_callback=callback) as client:
        result = await client.call_tool("check", {"path": str(target)})
        assert result.is_error is True
        assert isinstance(result.content[0], TextContent)
        assert "not within any declared root" in result.content[0].text


@pytest.mark.anyio
async def test_symlink_escaping_root_raises(tmp_path: Path):
    """A symlink inside a root that points outside should raise (resolve follows links)."""
    root_dir = tmp_path / "allowed"
    root_dir.mkdir()
    outside_dir = tmp_path / "forbidden"
    outside_dir.mkdir()
    outside_target = outside_dir / "secret.txt"
    outside_target.touch()

    link = root_dir / "escape"
    link.symlink_to(outside_target)

    server = MCPServer("test")

    @server.tool("check")
    async def check(context: Context, path: str) -> bool:
        await context.assert_within_roots(path)
        return True

    callback = _make_callback([Root(uri=FileUrl(f"file://{root_dir}"))])

    async with Client(server, list_roots_callback=callback) as client:
        result = await client.call_tool("check", {"path": str(link)})
        assert result.is_error is True


@pytest.mark.anyio
async def test_multiple_roots_any_match_passes(tmp_path: Path):
    """A path inside any one of several declared roots should pass."""
    root_a = tmp_path / "a"
    root_a.mkdir()
    root_b = tmp_path / "b"
    root_b.mkdir()
    target = root_b / "file.txt"
    target.touch()

    server = MCPServer("test")

    @server.tool("check")
    async def check(context: Context, path: str) -> bool:
        await context.assert_within_roots(path)
        return True

    callback = _make_callback(
        [
            Root(uri=FileUrl(f"file://{root_a}")),
            Root(uri=FileUrl(f"file://{root_b}")),
        ]
    )

    async with Client(server, list_roots_callback=callback) as client:
        result = await client.call_tool("check", {"path": str(target)})
        assert result.is_error is False
