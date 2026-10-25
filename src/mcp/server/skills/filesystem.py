"""`FilesystemSkillProvider`: a `SkillProvider` over a local directory."""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Sequence
from pathlib import Path

import anyio.to_thread

__all__ = ["FilesystemSkillProvider"]

logger = logging.getLogger(__name__)

# NONBLOCK keeps `open()` from hanging on a FIFO swapped in after listing; the `fstat` check then refuses it.
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)


# Windows junctions and symlinks are reparse points tagged IO_REPARSE_TAG_MOUNT_POINT / IO_REPARSE_TAG_SYMLINK,
# constants that `stat` only types on Windows. Other reparse points (cloud placeholders, dedup) are ordinary files.
_WINDOWS_LINK_REPARSE_TAGS = frozenset({0xA0000003, 0xA000000C})


class FilesystemSkillProvider:
    """A `SkillProvider` that reads skill files from a local directory.

    Only regular files are served. Symlinks (and Windows junctions) are never
    followed, so a skill directory can't expose files that live outside it; they
    are skipped with a warning when listing and refused when read. The blocking
    file system calls run in a worker thread.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        """Create a provider rooted at `root`. Nothing is read until `list_files()`."""
        self._root = Path(root).absolute()

    async def list_files(self) -> Sequence[str]:
        """Return the `/`-separated path of every regular file under the root, recursively.

        Entries whose name starts with `.` are not descended into or listed.

        Raises:
            OSError: If the root is missing, isn't a directory, or can't be read.
        """
        return await anyio.to_thread.run_sync(self._list_files)

    async def read_file(self, path: str) -> bytes:
        """Return the bytes of the regular file at `path`, relative to the root.

        Raises:
            ValueError: If `path` has an empty, `.` or `..` segment.
            OSError: If the file is missing, can't be read, is a symlink, or isn't a
                regular file, or if a directory on the way to it is a symlink.
        """
        segments = path.split("/")
        if any(segment in ("", ".", "..") for segment in segments):
            raise ValueError(f"invalid skill file path {path!r}")
        return await anyio.to_thread.run_sync(self._read_file, segments)

    def _list_files(self) -> list[str]:
        files: list[str] = []
        self._walk(self._root, [], files)
        return files

    def _walk(self, directory: Path, prefix: list[str], files: list[str]) -> None:
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name)
        for entry in ordered:
            if entry.name.startswith("."):
                continue
            segments = [*prefix, entry.name]
            result = entry.stat(follow_symlinks=False)
            if _is_link(result):
                logger.warning("Skipping symlink %s: skill files are never read through links", entry.path)
            elif stat.S_ISDIR(result.st_mode):
                self._walk(Path(entry.path), segments, files)
            elif stat.S_ISREG(result.st_mode):
                files.append("/".join(segments))
            else:  # pragma: lax no cover
                logger.warning("Skipping %s: not a regular file", entry.path)

    def _read_file(self, segments: list[str]) -> bytes:
        current = self._root
        for segment in segments[:-1]:
            current = current / segment
            result = os.lstat(current)
            if _is_link(result) or not stat.S_ISDIR(result.st_mode):
                raise OSError(f"{current} is not a plain directory")
        current = current / segments[-1]
        if _is_link(os.lstat(current)):
            raise OSError(f"{current} is a symlink")
        fd = os.open(current, _READ_FLAGS)
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise OSError(f"{current} is not a regular file")  # pragma: lax no cover
            return file.read()


def _is_link(result: os.stat_result) -> bool:
    return stat.S_ISLNK(result.st_mode) or getattr(result, "st_reparse_tag", 0) in _WINDOWS_LINK_REPARSE_TAGS
