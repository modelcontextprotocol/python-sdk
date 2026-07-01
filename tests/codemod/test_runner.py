"""File discovery, per-file isolation, and writing in `mcp_codemod._runner`."""

import textwrap
from pathlib import Path

import pytest
from inline_snapshot import snapshot
from mcp_codemod._runner import discover, run


def test_discover_yields_every_python_file_under_a_directory_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("")
    (tmp_path / "a.py").write_text("")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.py").write_text("")
    (tmp_path / "notes.txt").write_text("")

    assert list(discover([tmp_path])) == [tmp_path / "a.py", tmp_path / "b.py", tmp_path / "nested" / "c.py"]


def test_discover_prunes_vendored_directories(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "sub").mkdir(parents=True)
    (tmp_path / ".venv" / "sub" / "vendored.py").write_text("")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.py").write_text("")
    (tmp_path / "app.py").write_text("")

    assert list(discover([tmp_path])) == [tmp_path / "app.py"]


def test_discover_honours_an_explicitly_named_file(tmp_path: Path) -> None:
    """A path that is itself a file is yielded as-is, even without a `.py` suffix."""
    script = tmp_path / "script"
    script.write_text("x = 1\n")

    assert list(discover([script])) == [script]


def test_run_writes_only_the_files_that_changed(tmp_path: Path) -> None:
    v1_source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("legacy")
        """)
    v2_source = textwrap.dedent("""\
        from mcp.server.mcpserver import MCPServer

        app = MCPServer("already migrated")
        """)
    v1_path = tmp_path / "v1_module.py"
    v2_path = tmp_path / "v2_module.py"
    v1_path.write_text(v1_source)
    v2_path.write_text(v2_source)

    run([v1_path, v2_path], write=True)

    assert v1_path.read_text() == snapshot("""\
from mcp.server.mcpserver import MCPServer

server = MCPServer("legacy")
""")
    assert v2_path.read_text() == v2_source


def test_a_dry_run_leaves_every_file_untouched(tmp_path: Path) -> None:
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("legacy")
        """)
    path = tmp_path / "module.py"
    path.write_text(source)

    report = run([path], write=False)

    assert path.read_text() == source
    assert [file.path for file in report.changed] == [path]


def test_a_file_that_fails_to_parse_is_left_untouched_and_reported(tmp_path: Path) -> None:
    broken_source = "def (\n"
    broken_path = tmp_path / "broken.py"
    broken_path.write_text(broken_source)
    valid_path = tmp_path / "valid.py"
    valid_path.write_text(
        textwrap.dedent("""\
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("demo")
            """)
    )

    report = run([broken_path, valid_path], write=True)

    broken_report = report.files[0]
    assert broken_report.error is not None
    assert broken_report.result is None
    assert broken_path.read_text() == broken_source
    assert valid_path.read_text() == snapshot(
        """\
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo")
"""
    )


def test_the_report_aggregates_diagnostic_counts_by_severity(tmp_path: Path) -> None:
    """Flag-only sites count as `manual` and heuristic rewrites as `review` in the summed counts."""
    (tmp_path / "lowlevel.py").write_text(
        textwrap.dedent("""\
            from mcp.server.lowlevel import Server

            server = Server("demo")


            @traced
            @server.list_tools()
            async def handle_list_tools():
                return []
            """)
    )
    (tmp_path / "pagination.py").write_text(
        textwrap.dedent("""\
            from mcp.types import ListResourcesResult


            def cursor(result: ListResourcesResult) -> str | None:
                return result.nextCursor
            """)
    )

    report = run(discover([tmp_path]), write=False)

    assert report.diagnostics["manual"] >= 1
    assert report.diagnostics["review"] >= 1


def test_file_report_changed_is_false_for_an_untouched_file(tmp_path: Path) -> None:
    """`FileReport.changed` is true only when the transform succeeded and produced different code."""
    rewritten_path = tmp_path / "v1.py"
    rewritten_path.write_text("from mcp.types import Tool\n")
    untouched_source = "from mcp_types import Tool\n"
    untouched_path = tmp_path / "v2.py"
    untouched_path.write_text(untouched_source)
    broken_path = tmp_path / "broken.py"
    broken_path.write_text("def (\n")

    rewritten, untouched, broken = run([rewritten_path, untouched_path, broken_path], write=False).files

    assert rewritten.changed is True
    assert untouched.changed is False
    assert untouched.result is not None
    assert untouched.result.code == untouched_source
    assert broken.result is None
    assert broken.changed is False


def test_a_file_that_cannot_be_decoded_is_left_untouched_and_reported(tmp_path: Path) -> None:
    """A legal but non-UTF-8 file is recorded as failed and left as found, without aborting the run."""
    good = tmp_path / "aaa.py"
    good.write_text("from mcp.server.fastmcp import FastMCP\n")
    weird = tmp_path / "bbb.py"
    weird.write_bytes(b"# -*- coding: latin-1 -*-\n# caf\xe9\nX = 1\n")
    report = run([good, weird], write=True)
    assert "mcp.server.mcpserver" in good.read_text()
    assert weird.read_bytes() == b"# -*- coding: latin-1 -*-\n# caf\xe9\nX = 1\n"
    failed = report.files[1]
    assert failed.result is None
    assert failed.error is not None and "UnicodeDecodeError" in failed.error


def test_a_file_whose_write_fails_is_reported_without_aborting_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write failure is recorded as a write failure -- never a parse failure -- and the run continues."""
    first = tmp_path / "aaa.py"
    first.write_text("from mcp.server.fastmcp import FastMCP\n")
    second = tmp_path / "bbb.py"
    second.write_text("from mcp import McpError\n")
    real_write = Path.write_bytes

    def failing_write(self: Path, data: bytes) -> int:
        if self.name == "aaa.py":
            raise OSError(28, "No space left on device")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    report = run([first, second], write=True)
    failed = report.files[0]
    assert failed.result is None
    assert failed.error is not None and "write failed" in failed.error
    assert "MCPError" in second.read_text()


def test_crlf_line_endings_survive_a_rewrite(tmp_path: Path) -> None:
    """Files are read and written as bytes, so a CRLF file stays a CRLF file."""
    path = tmp_path / "win.py"
    path.write_bytes(b'from mcp.server.fastmcp import FastMCP\r\n\r\nmcp = FastMCP("demo")\r\n')
    run([path], write=True)
    assert path.read_bytes() == b'from mcp.server.mcpserver import MCPServer\r\n\r\nmcp = MCPServer("demo")\r\n'
