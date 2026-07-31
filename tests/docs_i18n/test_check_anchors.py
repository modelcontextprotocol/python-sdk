"""Tests for the heading-anchor check (scripts/docs/check_anchors.py): page discovery and the check."""

from pathlib import Path

import pytest
from check_anchors import check_pages, prose_pages


def test_check_pages_reports_missing_malformed_and_reused_anchors_with_repository_relative_posix_paths(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    page = docs / "servers" / "guide.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "# Guide {#guide}\n\n## First\n\n## Second {#bad!id}\n\n## Third {#guide}\n\n```md\n## code {#skipped}\n```\n",
        encoding="utf-8",
    )

    total, problems = check_pages([page], docs=docs)

    assert total == 4
    # The page reads as a repository path with `/` separators on every platform.
    assert problems == [
        "docs/servers/guide.md:3: heading has no {#anchor}: 'First'",
        'docs/servers/guide.md:5: #bad!id may only use letters, digits, "_", "-"',
        "docs/servers/guide.md:7: #guide already anchors line 1",
    ]


def test_prose_pages_ignores_dot_directories_inside_docs_but_not_the_ones_around_the_checkout(
    tmp_path: Path,
) -> None:
    # The checkout itself lives under a dot-directory (a build worktree does);
    # only dot-directories and the generated API tree *inside* docs are skipped.
    docs = tmp_path / ".worktrees" / "v2" / "docs"
    (docs / ".overrides").mkdir(parents=True)
    (docs / ".overrides" / "note.md").write_text("theme file", encoding="utf-8")
    (docs / "api").mkdir()
    (docs / "api" / "generated.md").write_text("generated reference", encoding="utf-8")
    (docs / "index.md").write_text("# Home {#home}\n", encoding="utf-8")
    (docs / "servers").mkdir()
    (docs / "servers" / "tools.md").write_text("# Tools {#tools}\n", encoding="utf-8")

    assert prose_pages(docs) == [docs / "index.md", docs / "servers" / "tools.md"]


def test_prose_pages_finding_no_pages_is_a_hard_error_not_a_silent_pass(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    with pytest.raises(SystemExit) as failure:
        prose_pages(docs)

    assert failure.value.code == f"check_anchors: found no prose pages under {docs} — is the docs tree in place?"
