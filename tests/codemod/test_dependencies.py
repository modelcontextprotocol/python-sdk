"""Dependency-file updating in `mcp_codemod._dependencies`."""

import textwrap
from pathlib import Path

from inline_snapshot import snapshot
from mcp_codemod._dependencies import update_dependencies


def _write(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content))
    return path


def test_a_v1_only_mcp_requirement_is_rewritten_to_the_v2_range(tmp_path: Path) -> None:
    """Only the specifier changes; the rest of the file keeps its exact formatting."""
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project]
        name = "demo"
        dependencies = [
            "httpx>=0.27",
            "mcp>=1.2,<2",
        ]
        """,
    )
    reports = update_dependencies([tmp_path], write=True)
    assert [report.changed for report in reports] == [True]
    assert pyproject.read_text() == snapshot(
        """\
[project]
name = "demo"
dependencies = [
    "httpx>=0.27",
    "mcp>=2,<3",
]
"""
    )


def test_a_requirement_that_already_admits_v2_is_untouched(tmp_path: Path) -> None:
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project]
        dependencies = ["mcp>=1.0", "anyio"]

        [project.optional-dependencies]
        bare = ["mcp"]
        """,
    )
    original = pyproject.read_text()
    assert update_dependencies([tmp_path], write=True) == []
    assert pyproject.read_text() == original


def test_extras_and_environment_markers_keep_their_original_spelling(tmp_path: Path) -> None:
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project]
        dependencies = ["mcp[cli,rich]==1.9.4 ; python_version >= '3.10'"]
        """,
    )
    update_dependencies([tmp_path], write=True)
    assert pyproject.read_text() == snapshot(
        """\
[project]
dependencies = ["mcp[cli,rich]>=2,<3 ; python_version >= '3.10'"]
"""
    )


def test_a_requirement_with_a_removed_extra_is_marked_not_rewritten(tmp_path: Path) -> None:
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project]
        dependencies = [
            "mcp[ws]>=1.2,<2",
        ]
        """,
    )
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert pyproject.read_text() == snapshot(
        """\
[project]
dependencies = [
    # mcp-codemod: the `ws` extra was removed with the WebSocket transport; set `mcp>=2,<3` by hand
    "mcp[ws]>=1.2,<2",
]
"""
    )


def test_optional_dependencies_and_dependency_groups_are_updated(tmp_path: Path) -> None:
    """An `include-group` table entry is passed over, not treated as a requirement."""
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project.optional-dependencies]
        server = ["mcp~=1.9"]

        [dependency-groups]
        dev = ["pytest", {include-group = "lint"}, "mcp==1.16.0"]
        lint = ["ruff"]
        """,
    )
    update_dependencies([tmp_path], write=True)
    content = pyproject.read_text()
    assert 'server = ["mcp>=2,<3"]' in content
    assert '"mcp>=2,<3"]' in content
    assert "1.16.0" not in content


def test_a_poetry_constraint_is_marked_for_a_hand_update(tmp_path: Path) -> None:
    """Poetry's own constraint syntax cannot be rewritten safely, so the entry is marked."""
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [tool.poetry.dependencies]
        python = "^3.10"
        mcp = "^1.2"
        """,
    )
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert pyproject.read_text() == snapshot(
        """\
[tool.poetry.dependencies]
python = "^3.10"
# mcp-codemod: update this Poetry constraint for v2 (`>=2,<3`) by hand
mcp = "^1.2"
"""
    )


def test_requirements_txt_lines_are_rewritten_and_keep_their_comments(tmp_path: Path) -> None:
    requirements = _write(
        tmp_path / "requirements.txt",
        """\
        -r base.txt
        httpx>=0.27
        mcp[cli]>=1.2,<2  # the SDK
        not a requirement!!
        """,
    )
    update_dependencies([tmp_path], write=True)
    assert requirements.read_text() == snapshot(
        """\
-r base.txt
httpx>=0.27
mcp[cli]>=2,<3  # the SDK
not a requirement!!
"""
    )


def test_a_requirements_line_with_a_removed_extra_is_marked(tmp_path: Path) -> None:
    requirements = _write(tmp_path / "requirements-dev.txt", "mcp[ws]==1.9.4\n")
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert requirements.read_text() == snapshot(
        """\
# mcp-codemod: the `ws` extra was removed with the WebSocket transport; set `mcp>=2,<3` by hand
mcp[ws]==1.9.4
"""
    )


def test_a_second_run_over_updated_files_is_a_noop(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["mcp[ws]<2", "mcp==1.9"]\n')
    _write(tmp_path / "requirements.txt", "mcp[ws]==1.9.4\nmcp==1.2\n")
    update_dependencies([tmp_path], write=True)
    first_pyproject = (tmp_path / "pyproject.toml").read_text()
    first_requirements = (tmp_path / "requirements.txt").read_text()
    update_dependencies([tmp_path], write=True)
    assert (tmp_path / "pyproject.toml").read_text() == first_pyproject
    assert (tmp_path / "requirements.txt").read_text() == first_requirements


def test_an_unparseable_pyproject_is_reported_and_left_untouched(tmp_path: Path) -> None:
    pyproject = _write(tmp_path / "pyproject.toml", "[project\ndependencies = [")
    original = pyproject.read_text()
    reports = update_dependencies([tmp_path], write=True)
    assert len(reports) == 1
    assert reports[0].error is not None and "TOMLDecodeError" in reports[0].error
    assert pyproject.read_text() == original


def test_nothing_is_written_when_write_is_false(tmp_path: Path) -> None:
    pyproject = _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["mcp<2"]\n')
    original = pyproject.read_text()
    reports = update_dependencies([tmp_path], write=False)
    assert reports[0].changed
    assert pyproject.read_text() == original


def test_dependency_files_inside_ignored_directories_are_skipped(tmp_path: Path) -> None:
    """A pyproject inside `.venv` or `node_modules` is vendored, not the user's."""
    (tmp_path / ".venv").mkdir()
    _write(tmp_path / ".venv" / "pyproject.toml", '[project]\ndependencies = ["mcp<2"]\n')
    assert update_dependencies([tmp_path], write=True) == []


def test_a_file_path_argument_yields_no_dependency_updates(tmp_path: Path) -> None:
    """Dependency files are discovered under directory arguments only."""
    target = tmp_path / "server.py"
    target.write_text("from mcp import ClientSession\n")
    assert update_dependencies([target], write=True) == []


def test_a_poetry_inline_dependency_table_still_gets_a_diagnostic(tmp_path: Path) -> None:
    """An inline table leaves no line to place a marker on, but the diagnostic still fires."""
    pyproject = _write(tmp_path / "pyproject.toml", '[tool.poetry]\ndependencies = { mcp = "^1.2" }\n')
    original = pyproject.read_text()
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert pyproject.read_text() == original


def test_a_requirement_hidden_behind_toml_escapes_is_left_alone(tmp_path: Path) -> None:
    """A raw TOML spelling that differs from its parsed value cannot be safely rewritten."""
    pyproject = _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["mcp \\u003c 2"]\n')
    original = pyproject.read_text()
    assert update_dependencies([tmp_path], write=True) == []
    assert pyproject.read_text() == original


def test_non_list_table_values_and_comment_lines_are_passed_over(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """\
        [project.optional-dependencies]
        weird = "not-a-list"

        [dependency-groups]
        odd = "also-not-a-list"
        """,
    )
    _write(tmp_path / "requirements.txt", "# just a comment\n\nhttpx\n")
    assert update_dependencies([tmp_path], write=True) == []


def test_add_markers_false_reports_without_writing_comments(tmp_path: Path) -> None:
    pyproject = _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["mcp[ws]<2"]\n')
    original = pyproject.read_text()
    reports = update_dependencies([tmp_path], write=True, add_markers=False)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert not reports[0].changed
    assert pyproject.read_text() == original


def test_constraints_already_on_v2_are_never_touched(tmp_path: Path) -> None:
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project]
        dependencies = ["mcp==2.1.4"]

        [project.optional-dependencies]
        alpha = ["mcp==2.0.0a1"]
        narrow = ["mcp>=2.1,<2.2"]
        """,
    )
    original = pyproject.read_text()
    assert update_dependencies([tmp_path], write=True) == []
    assert pyproject.read_text() == original


def test_a_removed_extra_is_flagged_even_when_the_specifier_admits_v2(tmp_path: Path) -> None:
    """On v2 the extra silently vanishes, so the extra check outranks the specifier check."""
    pyproject = _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["mcp[ws]>=1.0"]\n')
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert "# mcp-codemod:" in pyproject.read_text()
    assert "mcp[ws]>=1.0" in pyproject.read_text()


def test_a_url_requirement_is_flagged_not_rewritten(tmp_path: Path) -> None:
    """A VCS/URL reference has no specifier to rewrite but may pin v1 forever."""
    requirements = _write(tmp_path / "requirements.txt", "mcp @ git+https://github.com/o/r@v1.9.4\n")
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert "pins `mcp` by URL" in requirements.read_text()


def test_an_unparseable_mcp_line_is_flagged(tmp_path: Path) -> None:
    """Passing over an unparseable `mcp` line silently would hide a v1 pin."""
    requirements = _write(
        tmp_path / "requirements.txt",
        "httpx==0.27.0\nmcp==1.9.4 --hash=sha256:abc123\n",
    )
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    content = requirements.read_text()
    assert "could not parse this `mcp` line" in content
    assert "mcp==1.9.4 --hash=sha256:abc123" in content


def test_a_poetry_group_dependency_is_marked(tmp_path: Path) -> None:
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [tool.poetry.group.dev.dependencies]
        mcp = "^1.2"
        """,
    )
    reports = update_dependencies([tmp_path], write=True)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual"]
    assert "# mcp-codemod:" in pyproject.read_text()


def test_lookalike_strings_in_comments_and_other_tables_are_never_touched(tmp_path: Path) -> None:
    pyproject = _write(
        tmp_path / "pyproject.toml",
        """\
        [project]
        # keep "mcp>=1.2,<2" in sync with the docs
        dependencies = ["mcp>=1.2,<2"]

        [tool.mytool]
        note = "mcp>=1.2,<2"
        """,
    )
    update_dependencies([tmp_path], write=True)
    content = pyproject.read_text()
    assert '# keep "mcp>=1.2,<2" in sync with the docs' in content
    assert 'note = "mcp>=1.2,<2"' in content
    assert 'dependencies = ["mcp>=2,<3"]' in content


def test_an_arbitrary_equality_clause_is_left_alone(tmp_path: Path) -> None:
    """Nothing about an arbitrary-equality pin is provably v1-era."""
    pyproject = _write(tmp_path / "pyproject.toml", '[project]\ndependencies = ["mcp===legacy1"]\n')
    original = pyproject.read_text()
    assert update_dependencies([tmp_path], write=True) == []
    assert pyproject.read_text() == original


def test_two_poetry_tables_each_get_a_diagnostic(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """\
        [tool.poetry.dependencies]
        mcp = "^1.2"

        [tool.poetry.group.dev.dependencies]
        mcp = "^1.2"
        """,
    )
    reports = update_dependencies([tmp_path], write=True, add_markers=False)
    assert [diagnostic.severity for report in reports for diagnostic in report.diagnostics] == ["manual", "manual"]


def test_an_mcp_prefixed_other_package_is_untouched(tmp_path: Path) -> None:
    """Neither the rewrite nor the unparseable-line flag may fire on another distribution."""
    requirements = _write(tmp_path / "requirements.txt", "mcp-extra==1.0\n")
    assert update_dependencies([tmp_path], write=True) == []
    assert requirements.read_text() == "mcp-extra==1.0\n"
