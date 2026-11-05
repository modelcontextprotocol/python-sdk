import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mcp.server.mcpserver.resources import DirectoryResource


@pytest.fixture
def directory_with_files(tmp_path: Path) -> Path:
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("b", encoding="utf-8")
    return tmp_path


@pytest.fixture
def regular_file(tmp_path: Path) -> Path:
    path = tmp_path / "file.txt"
    path.write_text("content", encoding="utf-8")
    return path


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("recursive", "pattern", "expected"),
    [
        (False, None, ["a.txt", "z.txt"]),
        (True, None, ["a.txt", "nested/b.txt", "z.txt"]),
        (False, "*.txt", ["a.txt", "z.txt"]),
        (True, "*.txt", ["a.txt", "nested/b.txt", "z.txt"]),
    ],
)
async def test_directory_resource_returns_sorted_posix_file_paths(
    directory_with_files: Path, recursive: bool, pattern: str | None, expected: list[str]
) -> None:
    """SDK-defined listings contain sorted relative file paths for each glob mode."""
    resource = DirectoryResource(
        uri="test://directory", name="directory", path=directory_with_files, recursive=recursive, pattern=pattern
    )

    assert json.loads(await resource.read()) == {"files": expected}


@pytest.mark.anyio
async def test_directory_resource_rejects_missing_directory(tmp_path: Path) -> None:
    """SDK-defined directory reads report a missing path."""
    resource = DirectoryResource(uri="test://directory", name="directory", path=tmp_path / "missing")

    with pytest.raises(FileNotFoundError):
        await resource.read()


@pytest.mark.anyio
async def test_directory_resource_rejects_regular_file(regular_file: Path) -> None:
    """SDK-defined directory reads reject a regular file path."""
    resource = DirectoryResource(uri="test://directory", name="directory", path=regular_file)

    with pytest.raises(NotADirectoryError):
        await resource.read()


def test_directory_resource_requires_absolute_path() -> None:
    """SDK-defined resource validation rejects relative directory paths."""
    with pytest.raises(ValidationError):
        DirectoryResource(uri="test://directory", name="directory", path=Path("relative"))
