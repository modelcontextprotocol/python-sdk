"""Tests for `FilesystemSkillProvider` (`mcp.server.skills.filesystem`)."""

import logging
import os
import sys
from pathlib import Path

import pytest

from mcp.server.skills import FilesystemSkillProvider

pytestmark = pytest.mark.anyio

FILESYSTEM_LOGGER = "mcp.server.skills.filesystem"

requires_symlinks = pytest.mark.skipif(sys.platform == "win32", reason="creating symlinks needs privileges on Windows")
requires_fifos = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX-only")


async def test_list_files_returns_slash_separated_relative_paths_of_nested_files(tmp_path: Path) -> None:
    (tmp_path / "git-workflow" / "references").mkdir(parents=True)
    (tmp_path / "git-workflow" / "SKILL.md").write_bytes(b"skill")
    (tmp_path / "git-workflow" / "references" / "conventions.md").write_bytes(b"conventions")
    (tmp_path / "top.txt").write_bytes(b"top")

    files = await FilesystemSkillProvider(tmp_path).list_files()

    assert sorted(files) == ["git-workflow/SKILL.md", "git-workflow/references/conventions.md", "top.txt"]


async def test_list_files_prunes_hidden_entries(tmp_path: Path) -> None:
    """SDK-defined: hidden directories are never walked (so `.git` costs nothing)."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_bytes(b"x")
    (tmp_path / "skill").mkdir()
    (tmp_path / "skill" / ".env").write_bytes(b"x")
    (tmp_path / "skill" / "SKILL.md").write_bytes(b"x")

    assert await FilesystemSkillProvider(tmp_path).list_files() == ["skill/SKILL.md"]


@requires_symlinks
async def test_list_files_skips_symlinks_with_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: links are never followed, so a skill directory can't expose files outside the root."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    root = tmp_path / "root"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_bytes(b"x")
    (root / "skill" / "linked-file.txt").symlink_to(outside / "secret.txt")
    (root / "skill" / "linked-dir").symlink_to(outside, target_is_directory=True)

    with caplog.at_level(logging.WARNING, logger=FILESYSTEM_LOGGER):
        files = await FilesystemSkillProvider(root).list_files()

    assert files == ["skill/SKILL.md"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("linked-file.txt" in message for message in messages)
    assert any("linked-dir" in message for message in messages)


@requires_fifos
async def test_list_files_skips_a_named_pipe_with_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: only regular files are listed."""
    (tmp_path / "SKILL.md").write_bytes(b"x")
    os.mkfifo(tmp_path / "pipe")

    with caplog.at_level(logging.WARNING, logger=FILESYSTEM_LOGGER):
        files = await FilesystemSkillProvider(tmp_path).list_files()

    assert files == ["SKILL.md"]
    assert any("pipe" in record.getMessage() for record in caplog.records)


async def test_list_files_raises_os_error_for_a_missing_root(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path / "missing").list_files()


async def test_read_file_returns_the_raw_bytes(tmp_path: Path) -> None:
    (tmp_path / "skill").mkdir()
    content = b"\xef\xbb\xbfline\r\n\xff"
    (tmp_path / "skill" / "SKILL.md").write_bytes(content)

    assert await FilesystemSkillProvider(tmp_path).read_file("skill/SKILL.md") == content


@pytest.mark.parametrize("path", ["", "/skill/SKILL.md", "skill//SKILL.md", "./skill/SKILL.md", "skill/../SKILL.md"])
async def test_read_file_rejects_empty_dot_and_dot_dot_segments(tmp_path: Path, path: str) -> None:
    """SDK-defined: a path that could leave the root is refused before the file system is touched."""
    with pytest.raises(ValueError):
        await FilesystemSkillProvider(tmp_path).read_file(path)


async def test_read_file_raises_os_error_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file("missing.md")


@requires_symlinks
async def test_read_file_refuses_a_file_swapped_for_a_symlink_after_listing(tmp_path: Path) -> None:
    """SDK-defined: a symlink put in place of a listed file is not followed."""
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"secret")
    root = tmp_path / "root"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_bytes(b"x")
    provider = FilesystemSkillProvider(root)
    assert "skill/SKILL.md" in await provider.list_files()

    (root / "skill" / "SKILL.md").unlink()
    (root / "skill" / "SKILL.md").symlink_to(secret)

    with pytest.raises(OSError):
        await provider.read_file("skill/SKILL.md")


@requires_symlinks
async def test_read_file_refuses_a_directory_swapped_for_a_symlink_after_listing(tmp_path: Path) -> None:
    """SDK-defined: an intermediate directory replaced by a symlink is not traversed."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_bytes(b"secret")
    root = tmp_path / "root"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_bytes(b"x")
    provider = FilesystemSkillProvider(root)
    assert "skill/SKILL.md" in await provider.list_files()

    (root / "skill" / "SKILL.md").unlink()
    (root / "skill").rmdir()
    (root / "skill").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        await provider.read_file("skill/SKILL.md")


async def test_read_file_refuses_an_intermediate_component_that_is_a_file(tmp_path: Path) -> None:
    """SDK-defined: only directories are traversed on the way to a file."""
    (tmp_path / "skill").write_bytes(b"not a directory")

    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file("skill/SKILL.md")


async def test_read_file_refuses_a_directory(tmp_path: Path) -> None:
    """SDK-defined: only regular files are readable."""
    (tmp_path / "skill").mkdir()

    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file("skill")


@requires_fifos
async def test_read_file_refuses_a_named_pipe_without_blocking(tmp_path: Path) -> None:
    """SDK-defined: a pipe swapped in after listing is refused rather than waited on."""
    os.mkfifo(tmp_path / "pipe")

    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file("pipe")
