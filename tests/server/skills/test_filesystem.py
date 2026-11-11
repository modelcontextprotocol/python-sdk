"""Tests for `FilesystemSkillProvider` (`mcp.server.skills.filesystem`)."""

import logging
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp.server.skills import FilesystemSkillProvider

pytestmark = pytest.mark.anyio

FILESYSTEM_LOGGER = "mcp.server.skills.filesystem"

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_CLOUD_FILE = 0x9000601A  # OneDrive placeholder: a reparse point that is an ordinary file


def reparse_stat(mode: int, tag: int) -> Any:
    """A `stat` result for a Windows reparse point, which POSIX can't produce."""
    return SimpleNamespace(st_mode=mode, st_reparse_tag=tag)


def pretend_reparse_points(monkeypatch: pytest.MonkeyPatch, points: dict[str, tuple[int, int]]) -> None:
    """Make `os.scandir`/`os.lstat` report the named entries as Windows reparse points: `{name: (mode, tag)}`."""
    real_lstat = os.lstat
    real_scandir = os.scandir

    class Entry:
        def __init__(self, real: os.DirEntry[str]) -> None:
            self.real = real
            self.name = real.name
            self.path = real.path

        def stat(self, *, follow_symlinks: bool) -> Any:
            if self.name in points:
                return reparse_stat(*points[self.name])
            return self.real.stat(follow_symlinks=follow_symlinks)

    @contextmanager
    def scandir(path: Any) -> Iterator[list[Entry]]:
        with real_scandir(path) as entries:
            yield [Entry(entry) for entry in entries]

    def lstat(path: Any, *args: Any, **kwargs: Any) -> Any:
        name = Path(path).name
        if name in points:
            return reparse_stat(*points[name])
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "lstat", lstat)


async def test_list_files_returns_slash_separated_relative_paths_of_nested_files(tmp_path: Path) -> None:
    """SDK-defined: discovery returns portable paths relative to the configured root."""
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


async def test_list_files_skips_a_linked_directory_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """SDK-defined: links (symlinks, and junctions on Windows) are never followed, so a skill directory can't
    expose files outside the root."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    root = tmp_path / "root"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_bytes(b"x")
    shutil.copytree(outside, root / "skill" / "linked-dir")
    pretend_reparse_points(monkeypatch, {"linked-dir": (stat.S_IFLNK | 0o777, 0)})

    with caplog.at_level(logging.WARNING, logger=FILESYSTEM_LOGGER):
        files = await FilesystemSkillProvider(root).list_files()

    assert files == ["skill/SKILL.md"]
    assert any("linked-dir" in record.getMessage() for record in caplog.records)


async def test_list_files_skips_a_symlinked_file_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """SDK-defined: a file reported as a POSIX symlink is not listed, simulated without platform privileges."""
    (tmp_path / "secret.txt").write_bytes(b"secret")
    root = tmp_path / "root"
    root.mkdir()
    (root / "SKILL.md").write_bytes(b"x")
    (root / "linked-file.txt").write_bytes(b"secret")
    pretend_reparse_points(monkeypatch, {"linked-file.txt": (stat.S_IFLNK | 0o777, 0)})

    with caplog.at_level(logging.WARNING, logger=FILESYSTEM_LOGGER):
        files = await FilesystemSkillProvider(root).list_files()

    assert files == ["SKILL.md"]
    assert any("linked-file.txt" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("tag", [IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK], ids=["junction", "symlink"])
async def test_list_files_skips_a_windows_reparse_point_that_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tag: int
) -> None:
    """SDK-defined: Windows reports junctions and symlinks as reparse points with these tags, which
    POSIX can't create, so the platform's `stat` result is simulated."""
    (tmp_path / "skill").mkdir()
    (tmp_path / "skill" / "SKILL.md").write_bytes(b"x")
    (tmp_path / "junction").mkdir()
    (tmp_path / "junction" / "secret.txt").write_bytes(b"secret")
    pretend_reparse_points(monkeypatch, {"junction": (stat.S_IFDIR | 0o755, tag)})

    with caplog.at_level(logging.WARNING, logger=FILESYSTEM_LOGGER):
        files = await FilesystemSkillProvider(tmp_path).list_files()

    assert files == ["skill/SKILL.md"]
    assert any("junction" in record.getMessage() for record in caplog.records)


async def test_list_files_keeps_a_windows_reparse_point_that_is_not_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK-defined: cloud placeholders and similar reparse points are ordinary files, not links to refuse."""
    (tmp_path / "SKILL.md").write_bytes(b"x")
    (tmp_path / "placeholder.txt").write_bytes(b"x")
    pretend_reparse_points(monkeypatch, {"placeholder.txt": (stat.S_IFREG | 0o644, IO_REPARSE_TAG_CLOUD_FILE)})

    assert await FilesystemSkillProvider(tmp_path).list_files() == ["SKILL.md", "placeholder.txt"]


async def test_list_files_skips_a_named_pipe_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """SDK-defined: only regular files are listed; FIFO stat metadata is simulated on every platform."""
    (tmp_path / "SKILL.md").write_bytes(b"x")
    (tmp_path / "pipe").write_bytes(b"")
    pretend_reparse_points(monkeypatch, {"pipe": (stat.S_IFIFO | 0o600, 0)})

    with caplog.at_level(logging.WARNING, logger=FILESYSTEM_LOGGER):
        files = await FilesystemSkillProvider(tmp_path).list_files()

    assert files == ["SKILL.md"]
    assert any("pipe" in record.getMessage() for record in caplog.records)


async def test_list_files_raises_os_error_for_a_missing_root(tmp_path: Path) -> None:
    """SDK-defined: discovery propagates missing-root errors rather than serving an empty catalog."""
    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path / "missing").list_files()


async def test_read_file_returns_the_raw_bytes(tmp_path: Path) -> None:
    """SDK-defined: file reads preserve undecodable bytes and line endings."""
    (tmp_path / "skill").mkdir()
    content = b"\xef\xbb\xbfline\r\n\xff"
    (tmp_path / "skill" / "SKILL.md").write_bytes(content)

    assert await FilesystemSkillProvider(tmp_path).read_file("skill/SKILL.md") == content


@pytest.mark.parametrize("path", ["", "/skill/SKILL.md", "skill//SKILL.md", "./skill/SKILL.md", "skill/../SKILL.md"])
async def test_read_file_rejects_empty_dot_and_dot_dot_segments(tmp_path: Path, path: str) -> None:
    """SDK-defined: a path that could leave the root is refused before the file system is touched."""
    with pytest.raises(ValueError):
        await FilesystemSkillProvider(tmp_path).read_file(path)


@pytest.mark.parametrize("path", ["..\\secret.txt", "skill\\SKILL.md", "C:secret.txt", "skill/C:SKILL.md"])
async def test_read_file_refuses_windows_path_syntax_that_could_leave_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """SDK-defined: on Windows `\\` separates and `:` names a drive, so a "/"-only check would let these escape.

    The Windows rule is switched on here because the escape can't be shown from a POSIX path.
    """
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"outside the root")
    monkeypatch.setattr("mcp.server.skills.filesystem._FORBIDDEN_SEGMENT_CHARS", "\\:")

    with pytest.raises(ValueError):
        await FilesystemSkillProvider(root).read_file(path)


async def test_posix_path_validation_accepts_colons_and_backslashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK-defined: POSIX accepts these characters; simulate the I/O boundary because Windows cannot store them."""
    provider = FilesystemSkillProvider(tmp_path)
    segments_seen: list[list[str]] = []

    def read(segments: list[str]) -> bytes:
        segments_seen.append(segments)
        return b"content"

    monkeypatch.setattr("mcp.server.skills.filesystem._FORBIDDEN_SEGMENT_CHARS", "")
    monkeypatch.setattr(provider, "_read_file", read)
    assert await provider.read_file("skill/a:b\\c.md") == b"content"
    assert segments_seen == [["skill", "a:b\\c.md"]]


async def test_read_file_raises_os_error_for_a_missing_file(tmp_path: Path) -> None:
    """SDK-defined: reads propagate missing-file errors."""
    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file("missing.md")


async def test_read_file_refuses_a_file_swapped_for_a_symlink_after_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK-defined: POSIX symlink metadata appearing after listing is refused, simulated on every platform."""
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"secret")
    root = tmp_path / "root"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_bytes(b"x")
    provider = FilesystemSkillProvider(root)
    assert "skill/SKILL.md" in await provider.list_files()

    (root / "skill" / "SKILL.md").write_bytes(secret.read_bytes())
    pretend_reparse_points(monkeypatch, {"SKILL.md": (stat.S_IFLNK | 0o777, 0)})

    with pytest.raises(OSError):
        await provider.read_file("skill/SKILL.md")


async def test_read_file_refuses_a_final_component_that_is_a_linked_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK-defined: a final-component symlink is refused; simulate its stat metadata on every platform."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(outside, root / "linked")
    pretend_reparse_points(monkeypatch, {"linked": (stat.S_IFLNK | 0o777, 0)})

    with pytest.raises(OSError):
        await FilesystemSkillProvider(root).read_file("linked")


async def test_read_file_refuses_a_directory_swapped_for_a_link_after_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK-defined: an intermediate directory replaced by a link (a symlink, or a junction on Windows) is
    not traversed."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_bytes(b"secret")
    root = tmp_path / "root"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_bytes(b"x")
    provider = FilesystemSkillProvider(root)
    assert "skill/SKILL.md" in await provider.list_files()

    (root / "skill" / "SKILL.md").write_bytes((outside / "SKILL.md").read_bytes())
    pretend_reparse_points(monkeypatch, {"skill": (stat.S_IFLNK | 0o777, 0)})

    with pytest.raises(OSError):
        await provider.read_file("skill/SKILL.md")


@pytest.mark.parametrize("name", ["skill/junction/SKILL.md", "skill/junction"])
async def test_read_file_refuses_a_windows_reparse_point_that_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """SDK-defined: a junction, as an intermediate or final component, is refused (simulated, as above)."""
    (tmp_path / "skill" / "junction").mkdir(parents=True)
    (tmp_path / "skill" / "junction" / "SKILL.md").write_bytes(b"secret")
    pretend_reparse_points(monkeypatch, {"junction": (stat.S_IFDIR | 0o755, IO_REPARSE_TAG_MOUNT_POINT)})

    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file(name)


async def test_read_file_reads_a_windows_reparse_point_that_is_not_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK-defined: a cloud placeholder is an ordinary file and is read normally."""
    (tmp_path / "placeholder.txt").write_bytes(b"content")
    pretend_reparse_points(monkeypatch, {"placeholder.txt": (stat.S_IFREG | 0o644, IO_REPARSE_TAG_CLOUD_FILE)})

    assert await FilesystemSkillProvider(tmp_path).read_file("placeholder.txt") == b"content"


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


async def test_read_file_refuses_a_non_regular_open_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK-defined: fstat rejects a non-regular descriptor even when lstat reported a regular file."""
    (tmp_path / "pipe").write_bytes(b"must not be read")

    def fstat(fd: int) -> Any:
        return reparse_stat(stat.S_IFIFO | 0o600, 0)

    monkeypatch.setattr(os, "fstat", fstat)

    with pytest.raises(OSError):
        await FilesystemSkillProvider(tmp_path).read_file("pipe")


async def test_a_root_that_is_itself_a_link_is_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK-defined: trusted-root link metadata is not refused; simulate it without needing link privileges."""
    real = tmp_path / "real"
    (real / "skill").mkdir(parents=True)
    (real / "skill" / "SKILL.md").write_bytes(b"x")
    link = tmp_path / "link"
    shutil.copytree(real, link)
    pretend_reparse_points(monkeypatch, {"link": (stat.S_IFLNK | 0o777, 0)})

    provider = FilesystemSkillProvider(link)

    assert await provider.list_files() == ["skill/SKILL.md"]
    assert await provider.read_file("skill/SKILL.md") == b"x"
