"""The storage interface behind `SkillCatalog`."""

from collections.abc import Sequence
from typing import Protocol

__all__ = ["SkillProvider"]


class SkillProvider(Protocol):
    """A source of skill files.

    Implementations are structural: they need not subclass this class. A path is a
    `/`-separated string relative to the provider's root, with no leading `/` and
    no empty, `.` or `..` segment. A provider reports paths exactly as stored;
    it neither parses skills nor decides which files belong to which skill.
    """

    async def list_files(self) -> Sequence[str]:
        """Return the path of every file the provider serves, recursively.

        Directories are not listed, and each path appears once. A provider may leave files out;
        `FilesystemSkillProvider` omits any name that starts with `.`.
        """
        ...

    async def read_file(self, path: str) -> bytes:
        """Return the raw, undecoded bytes of the file at `path`.

        Raises:
            OSError: If the file can't be read.
        """
        ...
