"""Apply the v1 -> v2 transformer to files on disk."""

import os
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from libcst import ParserSyntaxError

from mcp_codemod._transformer import Result, transform

__all__ = ["IGNORED_DIRECTORIES", "FileReport", "RunReport", "discover", "run"]

IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".eggs",
        ".git",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
    }
)


@dataclass(frozen=True, slots=True)
class FileReport:
    """The outcome for one file. `error` is set instead of a result when it failed."""

    path: Path
    original: str
    result: Result | None
    error: str | None

    @property
    def changed(self) -> bool:
        """Whether the transformed code differs from what was read."""
        return self.result is not None and self.result.code != self.original


@dataclass(frozen=True, slots=True)
class RunReport:
    """Everything `run()` did, in the order the files were visited."""

    files: list[FileReport]

    @property
    def changed(self) -> list[FileReport]:
        return [report for report in self.files if report.changed]

    @property
    def failed(self) -> list[FileReport]:
        return [report for report in self.files if report.error is not None]

    @property
    def diagnostics(self) -> Counter[str]:
        """Diagnostic counts across every file, keyed by severity."""
        counts: Counter[str] = Counter()
        for report in self.files:
            if report.result is not None:
                counts.update(diagnostic.severity for diagnostic in report.result.diagnostics)
        return counts


def discover(paths: Sequence[Path]) -> Iterator[Path]:
    """Yield every Python file under `paths`, pruning vendored and build directories.

    A path that is itself a file is yielded as-is, even without a `.py` suffix.
    """
    for path in paths:
        if path.is_dir():
            found: list[Path] = []
            for directory, child_directories, files in os.walk(path):
                child_directories[:] = [name for name in child_directories if name not in IGNORED_DIRECTORIES]
                found.extend(Path(directory, name) for name in files if name.endswith(".py"))
            yield from sorted(found)
        else:
            yield path


def run(paths: Iterable[Path], *, write: bool, add_markers: bool = True) -> RunReport:
    """Transform every discovered file, writing the results back when `write` is true.

    Failures are recorded per file; the run continues to the next file.
    """
    reports: list[FileReport] = []
    for path in paths:
        source = ""
        try:
            # UTF-8 bytes rather than `read_text()`: locale-independent, and line endings round-trip unchanged.
            source = path.read_bytes().decode("utf-8")
            result = transform(source, add_markers=add_markers)
        except (OSError, UnicodeDecodeError, ParserSyntaxError) as exc:
            reports.append(FileReport(path, source, None, f"{type(exc).__name__}: {exc}"))
            continue
        report = FileReport(path, source, result, None)
        if write and report.changed:
            try:
                path.write_bytes(result.code.encode("utf-8"))
            except OSError as exc:
                error = f"the write failed and the file on disk may be incomplete: {exc}"
                reports.append(FileReport(path, source, None, error))
                continue
        reports.append(report)
    return RunReport(reports)
