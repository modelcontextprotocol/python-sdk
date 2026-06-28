"""The `mcp-codemod` command line: its flags, output, and exit codes."""

import textwrap
from pathlib import Path

import pytest
from mcp_codemod.cli import main


def test_v1_to_v2_rewrites_files_and_prints_a_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`v1-to-v2` rewrites a v1 file in place and the summary says how many files changed."""
    path = tmp_path / "server.py"
    path.write_text("from mcp.server.fastmcp import FastMCP\n")

    assert main(["v1-to-v2", str(tmp_path)]) == 0

    assert "mcp.server.mcpserver" in path.read_text()
    assert "1 of 1 files rewritten" in capsys.readouterr().out


def test_dry_run_reports_without_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--dry-run` reports what would change but leaves the file exactly as it was."""
    source = "from mcp.server.fastmcp import FastMCP\n"
    path = tmp_path / "server.py"
    path.write_text(source)

    assert main(["v1-to-v2", "--dry-run", str(tmp_path)]) == 0

    assert path.read_text() == source
    assert "Dry run" in capsys.readouterr().out


def test_diff_prints_a_unified_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--diff` prints a unified diff removing the v1 import and adding the v2 one."""
    path = tmp_path / "server.py"
    path.write_text("from mcp.server.fastmcp import FastMCP\n")

    main(["v1-to-v2", "--diff", str(tmp_path)])

    out = capsys.readouterr().out
    assert "-from mcp.server.fastmcp import FastMCP\n" in out
    assert "+from mcp.server.mcpserver import MCPServer\n" in out


def test_no_markers_suppresses_comment_insertion(tmp_path: Path) -> None:
    """`--no-markers` still rewrites the file but inserts no `# mcp-codemod:` comment at the site needing a human."""
    path = tmp_path / "server.py"
    path.write_text(
        textwrap.dedent("""\
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("demo", mount_path="/old")
            """)
    )

    main(["v1-to-v2", "--no-markers", str(tmp_path)])

    rewritten = path.read_text()
    assert "mcp.server.mcpserver" in rewritten
    assert "# mcp-codemod" not in rewritten


def test_a_parse_failure_returns_a_nonzero_exit_and_is_reported_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file that fails to parse makes `main` return 1 and is named on stderr."""
    path = tmp_path / "broken.py"
    path.write_text("def broken(:\n")

    assert main(["v1-to-v2", str(tmp_path)]) == 1

    assert str(path) in capsys.readouterr().err


def test_version_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    """`--version` prints `mcp-codemod <version>` from the installed distribution and exits."""
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("mcp-codemod ")


def test_a_missing_migration_argument_is_an_argparse_error() -> None:
    """Invoking the CLI without naming a migration is an argparse usage error with exit code 2."""
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_the_grep_hint_appears_only_when_there_are_markers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The `grep -rn '# mcp-codemod:'` follow-up hint is printed only when some site still needs a human."""
    clean = tmp_path / "clean.py"
    clean.write_text('from mcp.server.mcpserver import MCPServer\n\nmcp = MCPServer("demo")\n')
    assert main(["v1-to-v2", str(clean)]) == 0
    assert "grep -rn" not in capsys.readouterr().out

    flagged = tmp_path / "flagged.py"
    flagged.write_text(
        textwrap.dedent("""\
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("demo", port=8000)
        """)
    )
    assert main(["v1-to-v2", str(flagged)]) == 0
    assert "grep -rn '# mcp-codemod:'" in capsys.readouterr().out


def test_the_per_file_line_reports_review_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A file whose rewrite rests on a heuristic gets a per-file line counting the sites that need review."""
    path = tmp_path / "pager.py"
    path.write_text(
        textwrap.dedent("""\
            from mcp.types import ListToolsResult

            def next_page(result: ListToolsResult) -> str | None:
                return result.nextCursor
        """)
    )
    assert main(["v1-to-v2", str(path)]) == 0
    [file_line] = [line for line in capsys.readouterr().out.splitlines() if line.startswith(f"{path}:")]
    assert file_line.endswith("1 need review")


def test_an_unchanged_file_with_no_diagnostics_produces_no_per_file_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An already-v2 file is counted in the run total but never gets its own per-file count line."""
    path = tmp_path / "clean.py"
    path.write_text('from mcp.server.mcpserver import MCPServer\n\nmcp = MCPServer("demo")\n')
    assert main(["v1-to-v2", str(path)]) == 0
    out = capsys.readouterr().out
    assert "0 of 1 files rewritten" in out
    assert f"{path}:" not in out


def test_diff_skips_files_the_codemod_did_not_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--diff` prints a hunk only for the files that changed, so an already-migrated
    file sitting next to a v1 one contributes nothing to the diff output."""
    (tmp_path / "old.py").write_text("from mcp.server.fastmcp import FastMCP\n")
    (tmp_path / "new.py").write_text("from mcp.server.mcpserver import MCPServer\n")
    assert main(["v1-to-v2", "--diff", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"--- {tmp_path / 'old.py'}" in out
    assert f"--- {tmp_path / 'new.py'}" not in out


def test_a_dry_run_lists_every_site_instead_of_the_grep_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With `--dry-run` no marker lands on disk, so the grep hint would find
    nothing; the summary lists each site that needs a human directly instead.
    Renames reported only for the record (`info`) are not part of that list.
    """
    target = tmp_path / "server.py"
    target.write_text(
        'from mcp.server.fastmcp import FastMCP\n\nmcp = FastMCP("demo", mount_path="/x")\nprint(tool.inputSchema)\n'
    )
    broken = tmp_path / "broken.py"
    broken.write_text("def (\n")
    code = main(["v1-to-v2", "--dry-run", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert f"{target}:3: `mount_path=`" in captured.out
    assert "inputSchema" not in captured.out
    assert "grep -rn" not in captured.out
    assert "Dry run: nothing was written." in captured.out
    assert "failed (" in captured.err


def test_the_cli_updates_dependency_files_alongside_the_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One run migrates the code and the project's `mcp` requirement together, and
    a dependency flag joins the still-need-a-human accounting.
    """
    (tmp_path / "server.py").write_text("from mcp.server.fastmcp import FastMCP\n")
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["mcp>=1.2,<2"]\n')
    (tmp_path / "requirements.txt").write_text("mcp[ws]==1.9.4\n")
    code = main(["v1-to-v2", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "mcp.server.mcpserver" in (tmp_path / "server.py").read_text()
    assert '"mcp>=2,<3"' in (tmp_path / "pyproject.toml").read_text()
    assert "# mcp-codemod:" in (tmp_path / "requirements.txt").read_text()
    assert f"{tmp_path / 'pyproject.toml'}: mcp requirement updated for v2" in captured.out
    assert f"{tmp_path / 'requirements.txt'}: 1 need review" in captured.out
    assert "1 sites still need a human" in captured.out


def test_a_broken_pyproject_fails_the_run_without_stopping_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unparseable dependency file is reported on stderr and sets the exit code,
    while the source files still migrate."""
    (tmp_path / "server.py").write_text("from mcp.server.fastmcp import FastMCP\n")
    (tmp_path / "pyproject.toml").write_text("[broken")
    code = main(["v1-to-v2", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert "mcp.server.mcpserver" in (tmp_path / "server.py").read_text()
    assert "TOMLDecodeError" in captured.err


def test_no_markers_lists_dependency_sites_in_the_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Under `--no-markers` a dependency flag cannot live in the file, so the
    summary lists it with its location like any other site."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("mcp[ws]==1.9.4\n")
    code = main(["v1-to-v2", "--no-markers", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert requirements.read_text() == "mcp[ws]==1.9.4\n"
    assert f"{requirements}:1: the `ws` extra was removed" in captured.out
