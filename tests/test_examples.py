"""Tests for example servers"""
# TODO(Marcelo): The `examples` directory needs to be importable as a package.
# pyright: reportMissingImports=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from pathlib import Path

import pytest
from inline_snapshot import snapshot
from pytest_examples import CodeExample, EvalExample, find_examples

from mcp import Client
from mcp.types import CallToolResult, TextContent, TextResourceContents


@pytest.mark.anyio
async def test_simple_echo():
    """Test the simple echo server"""
    from examples.mcpserver.simple_echo import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("echo", {"text": "hello"})
        assert result == snapshot(
            CallToolResult(content=[TextContent(text="hello")], structured_content={"result": "hello"})
        )


@pytest.mark.anyio
async def test_complex_inputs():
    """Test the complex inputs server"""
    from examples.mcpserver.complex_inputs import mcp

    async with Client(mcp) as client:
        tank = {"shrimp": [{"name": "bob"}, {"name": "alice"}]}
        result = await client.call_tool("name_shrimp", {"tank": tank, "extra_names": ["charlie"]})
        assert result == snapshot(
            CallToolResult(
                content=[
                    TextContent(text="bob"),
                    TextContent(text="alice"),
                    TextContent(text="charlie"),
                ],
                structured_content={"result": ["bob", "alice", "charlie"]},
            )
        )


@pytest.mark.anyio
async def test_direct_call_tool_result_return():
    """Test the CallToolResult echo server"""
    from examples.mcpserver.direct_call_tool_result_return import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("echo", {"text": "hello"})
        assert result == snapshot(
            CallToolResult(
                meta={"some": "metadata"},  # type: ignore[reportUnknownMemberType]
                content=[TextContent(text="hello")],
                structured_content={"text": "hello"},
            )
        )


@pytest.mark.anyio
async def test_desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test the desktop server"""
    # Build a real Desktop directory under tmp_path rather than patching
    # Path.iterdir — a class-level patch breaks jsonschema_specifications'
    # import-time schema discovery when this test happens to be the first
    # tool call in an xdist worker.
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "file1.txt").touch()
    (desktop / "file2.txt").touch()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    from examples.mcpserver.desktop import mcp

    async with Client(mcp) as client:
        # Test the sum function
        result = await client.call_tool("sum", {"a": 1, "b": 2})
        assert result == snapshot(CallToolResult(content=[TextContent(text="3")], structured_content={"result": 3}))

        # Test the desktop resource
        result = await client.read_resource("dir://desktop")
        assert len(result.contents) == 1
        content = result.contents[0]
        assert isinstance(content, TextResourceContents)
        assert isinstance(content.text, str)
        assert "file1.txt" in content.text
        assert "file2.txt" in content.text


# TODO(v2): Change back to README.md when v2 is released
@pytest.mark.parametrize("example", find_examples("README.v2.md"), ids=str)
def test_docs_examples(example: CodeExample, eval_example: EvalExample):
    ruff_ignore: list[str] = ["F841", "I001", "F821"]  # F821: undefined names (snippets lack imports)

    # Use project's actual line length of 120
    eval_example.set_config(ruff_ignore=ruff_ignore, target_version="py310", line_length=120)

    # Use Ruff for both formatting and linting (skip Black)
    if eval_example.update_examples:  # pragma: no cover
        eval_example.format_ruff(example)
    else:
        eval_example.lint_ruff(example)
