"""Tests for example servers"""
# TODO(Marcelo): The `examples` directory needs to be importable as a package.
# pyright: reportMissingImports=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

import sys
from pathlib import Path
from typing import Any

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
async def test_desktop(monkeypatch: pytest.MonkeyPatch):
    """Test the desktop server"""
    # Mock desktop directory listing
    mock_files = [Path("/fake/path/file1.txt"), Path("/fake/path/file2.txt")]
    monkeypatch.setattr(Path, "iterdir", lambda self: mock_files)  # type: ignore[reportUnknownArgumentType]
    monkeypatch.setattr(Path, "home", lambda: Path("/fake/home"))

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
        if sys.platform == "win32":  # pragma: no cover
            file_1 = "/fake/path/file1.txt".replace("/", "\\\\")  # might be a bug
            file_2 = "/fake/path/file2.txt".replace("/", "\\\\")  # might be a bug
            assert file_1 in content.text
            assert file_2 in content.text
            # might be a bug, but the test is passing
        else:  # pragma: lax no cover
            assert "/fake/path/file1.txt" in content.text
            assert "/fake/path/file2.txt" in content.text


SKIP_RUN_TAGS = ["skip", "skip-run"]
SKIP_LINT_TAGS = ["skip", "skip-lint"]

# Files with code examples that are both linted and run
DOCS_FILES = ["docs/quickstart.md", "docs/concepts.md"]


def _set_eval_config(eval_example: EvalExample) -> None:
    eval_example.set_config(
        ruff_ignore=["F841", "I001", "F821"],
        target_version="py310",
        line_length=120,
    )


# TODO(v2): Change back to README.md when v2 is released
@pytest.mark.parametrize(
    "example",
    find_examples("README.v2.md", *DOCS_FILES),
    ids=str,
)
def test_docs_examples(example: CodeExample, eval_example: EvalExample):
    if any(example.prefix_settings().get(key) == "true" for key in SKIP_LINT_TAGS):
        pytest.skip("skip-lint")

    _set_eval_config(eval_example)

    if eval_example.update_examples:  # pragma: no cover
        eval_example.format_ruff(example)
    else:
        eval_example.lint_ruff(example)


def _get_runnable_docs_examples() -> list[CodeExample]:
    examples = find_examples(*DOCS_FILES)
    return [ex for ex in examples if not any(ex.prefix_settings().get(key) == "true" for key in SKIP_RUN_TAGS)]


@pytest.mark.parametrize("example", _get_runnable_docs_examples(), ids=str)
def test_docs_examples_run(example: CodeExample, eval_example: EvalExample):
    _set_eval_config(eval_example)

    # Prevent `if __name__ == "__main__"` blocks from starting servers
    globals: dict[str, Any] = {"__name__": "__docs_test__"}

    if eval_example.update_examples:  # pragma: no cover
        eval_example.run_print_update(example, module_globals=globals)
    else:
        eval_example.run_print_check(example, module_globals=globals)
