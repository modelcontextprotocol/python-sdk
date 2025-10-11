"""Tests for example servers"""

# TODO(Marcelo): The `examples` directory needs to be importable as a package.
# pyright: reportMissingImports=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
import sys
from pathlib import Path

import pytest
from pydantic import AnyUrl
from pytest_examples import CodeExample, EvalExample, find_examples

from examples.fastmcp.desktop import mcp
from mcp.shared.memory import create_connected_server_and_client_session as client_session
from mcp.types import TextContent, TextResourceContents


@pytest.mark.anyio
async def test_simple_echo():
    """Test the simple echo server"""
    from examples.fastmcp.simple_echo import mcp

    async with client_session(mcp._mcp_server) as client:
        result = await client.call_tool("echo", {"text": "hello"})
        assert len(result.content) == 1
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "hello"


@pytest.mark.anyio
async def test_complex_inputs():
    """Test the complex inputs server"""
    from examples.fastmcp.complex_inputs import mcp

    async with client_session(mcp._mcp_server) as client:
        tank = {"shrimp": [{"name": "bob"}, {"name": "alice"}]}
        result = await client.call_tool("name_shrimp", {"tank": tank, "extra_names": ["charlie"]})
        assert len(result.content) == 3
        assert isinstance(result.content[0], TextContent)
        assert isinstance(result.content[1], TextContent)
        assert isinstance(result.content[2], TextContent)
        assert result.content[0].text == "bob"
        assert result.content[1].text == "alice"
        assert result.content[2].text == "charlie"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "files",
    [
        pytest.param(
            ["/fake/path/file1.txt", "/fake/path/file2.txt"],
            id="unix",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test"),
        ),
        pytest.param(
            ["C:\\fake\\path\\file1.txt", "C:\\fake\\path\\file2.txt"],
            id="windows",
            marks=pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test"),
        ),
    ],
)
async def test_desktop(monkeypatch: pytest.MonkeyPatch, files: list[str]):
    """Test the desktop server"""

    # Mock desktop directory listing
    mock_files = [Path("/fake/path/file1.txt"), Path("/fake/path/file2.txt")]
    monkeypatch.setattr(Path, "iterdir", lambda self: mock_files)  # type: ignore[reportUnknownArgumentType]
    monkeypatch.setattr(Path, "home", lambda: Path("/fake/home"))

    async with client_session(mcp._mcp_server) as client:
        # Test the sum function
        result = await client.call_tool("sum", {"a": 1, "b": 2})
        assert len(result.content) == 1
        content = result.content[0]
        assert isinstance(content, TextContent)
        assert content.text == "3"

        # Test the desktop resource
        result = await client.read_resource(AnyUrl("dir://desktop"))
        assert len(result.contents) == 1
        content = result.contents[0]
        assert isinstance(content, TextResourceContents)
        assert isinstance(content.text, str)
        assert all(file in content.text for file in files)


@pytest.mark.parametrize("example", find_examples("README.md"), ids=str)
def test_docs_examples(example: CodeExample, eval_example: EvalExample):
    ruff_ignore: list[str] = ["F841", "I001", "F821"]  # F821: undefined names (snippets lack imports)

    # Use project's actual line length of 120
    eval_example.set_config(ruff_ignore=ruff_ignore, target_version="py310", line_length=120)

    # Use Ruff for both formatting and linting (skip Black)
    if eval_example.update_examples:  # pragma: no cover
        eval_example.format_ruff(example)
    else:
        eval_example.lint_ruff(example)
