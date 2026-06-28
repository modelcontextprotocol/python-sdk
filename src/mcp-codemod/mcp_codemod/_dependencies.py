"""Update a project's dependency declarations for the v2 SDK.

`update_dependencies()` finds every `pyproject.toml` and `requirements*.txt`
under the given paths and rewrites the `mcp` requirement to `>=2,<3` wherever
its current specifier cannot accept any v2 release; a constraint that already
admits v2 is left exactly as written. Only the specifier changes -- the
requirement's name, extras, and environment marker keep their original
spelling. Anything that cannot be rewritten safely (a removed extra, a Poetry
dependency table) is marked with a `# mcp-codemod:` comment instead, the same
contract the source transformer follows.
"""

import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

import tomllib
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from mcp_codemod._mappings import REMOVED_EXTRAS
from mcp_codemod._runner import IGNORED_DIRECTORIES
from mcp_codemod._transformer import MARKER, Diagnostic

__all__ = ["DependencyReport", "update_dependencies"]

V2_SPECIFIER = ">=2,<3"

# Probes used to classify a specifier. A constraint is only rewritten when it
# provably belongs to the v1 era (it admits a v1 release, or every version it
# spells has major < 2) AND provably admits no v2 release; anything else --
# `==2.1.4`, `>=2.1,<2.2`, the published `==2.0.0a1` -- is the user's own v2
# choice and is never touched.
_V1_PROBES = ("1.0.0", "1.99.99")
_V2_PROBES = ("2.0.0a1", "2.0.0", "2.99.99")

# The name-plus-extras prefix of a requirement string this module already
# validated with `Requirement`, used to splice a new specifier in behind it.
_REQUIREMENT_PREFIX = re.compile(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*(\[[^\]]*\])?")

# A `mcp = ...` key in a Poetry dependency table, which uses its own constraint
# syntax this module does not rewrite.
_POETRY_MCP_KEY = re.compile(r"^[ \t]*([\"']?)mcp\1[ \t]*=", re.MULTILINE)

# A requirements.txt line that NAMES mcp but did not parse as a requirement
# (pip-compile continuations, `--hash=` options, URL forms): it cannot be
# rewritten, but passing it over silently would hide a v1 pin.
_UNPARSEABLE_MCP_LINE = re.compile(r"^\s*mcp\b", re.IGNORECASE)

# The pyproject tables whose arrays hold PEP 508 strings; replacements and
# markers stay inside them so a lookalike string in a comment or some other
# tool's table is never touched.
_DEPENDENCY_TABLES = re.compile(r"^(project|project\.optional-dependencies|dependency-groups)$")


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """The outcome for one dependency file. `error` is set when it failed."""

    path: Path
    original: str
    updated: str | None
    diagnostics: list[Diagnostic]
    error: str | None

    @property
    def changed(self) -> bool:
        """Whether the updated text differs from what was read."""
        return self.updated is not None and self.updated != self.original


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _needs_v2(requirement: Requirement) -> bool:
    """Whether the constraint is a v1-era one that excludes every v2 release.

    An empty specifier admits everything, and a constraint that is not provably
    from the v1 era (an exact v2 pin, a narrow v2 range) is the user's own v2
    choice, so both are left exactly as written.
    """
    specifier = requirement.specifier
    if not str(specifier):
        return False
    if any(specifier.contains(probe, prereleases=True) for probe in _V2_PROBES):
        return False
    v1_era = any(specifier.contains(probe, prereleases=True) for probe in _V1_PROBES)
    for clause in specifier:
        try:
            spelled_version = Version(clause.version.rstrip(".*"))
        except InvalidVersion:
            continue
        v1_era = v1_era or spelled_version.major < 2
    return v1_era


def _rewrite_specifier(spelled: str) -> str:
    """Replace the specifier in a validated requirement string, keeping the rest.

    The name, extras, environment marker, and even the spacing around `;` are
    the user's own spelling and survive; only the version constraint changes.
    """
    base, separator, env_marker = spelled.partition(";")
    prefix = _REQUIREMENT_PREFIX.match(base)
    assert prefix is not None  # `Requirement` accepted it, so the prefix parses
    spacing = base[len(base.rstrip()) :]
    return f"{prefix.group(0)}{V2_SPECIFIER}{spacing}{separator}{env_marker}"


def _insert_marker_above(text: str, index: int, message: str) -> str:
    """Insert a `# mcp-codemod:` comment line above the line containing `index`."""
    line_start = text.rfind("\n", 0, index) + 1
    line = text[line_start:]
    indent = line[: len(line) - len(line.lstrip())]
    ending = "\r\n" if text[line_start:].partition("\n")[0].endswith("\r") else "\n"
    comment = f"{indent}# {MARKER}: {message}{ending}"
    if comment in text:
        return text
    return text[:line_start] + comment + text[line_start:]


def _mcp_requirement(spelled: str) -> Requirement | None:
    """Parse a dependency string, returning it only when it names `mcp` itself."""
    try:
        requirement = Requirement(spelled)
    except InvalidRequirement:
        return None
    return requirement if canonicalize_name(requirement.name) == "mcp" else None


def _is_table(value: object) -> TypeGuard[dict[str, object]]:
    """Whether a parsed TOML value is a table (its keys are strings by grammar)."""
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _pyproject_dependency_strings(parsed: dict[str, object]) -> Iterator[str]:
    """Every PEP 508 string in the standard dependency tables of a pyproject."""
    project = parsed.get("project")
    if _is_table(project):
        dependencies = project.get("dependencies")
        if _is_array(dependencies):
            yield from (entry for entry in dependencies if isinstance(entry, str))
        optional = project.get("optional-dependencies")
        if _is_table(optional):
            for group in optional.values():
                if _is_array(group):
                    yield from (entry for entry in group if isinstance(entry, str))
    groups = parsed.get("dependency-groups")
    if _is_table(groups):
        for group in groups.values():
            if _is_array(group):
                # A group entry may also be an `{include-group = ...}` table.
                yield from (entry for entry in group if isinstance(entry, str))


def _has_poetry_mcp(parsed: dict[str, object]) -> bool:
    """Whether any Poetry dependency table (main, legacy dev, or group) names mcp."""
    tool = parsed.get("tool")
    poetry = tool.get("poetry") if _is_table(tool) else None
    if not _is_table(poetry):
        return False
    tables = [poetry.get("dependencies"), poetry.get("dev-dependencies")]
    groups = poetry.get("group")
    if _is_table(groups):
        tables.extend(group.get("dependencies") for group in groups.values() if _is_table(group))
    return any(_is_table(table) and "mcp" in table for table in tables)


def _dependency_region_occurrences(text: str, quoted: str) -> list[int]:
    """Offsets of `quoted` inside the standard dependency tables, comments excluded.

    Scanning by table keeps a lookalike string in some other tool's table or in
    a TOML comment out of reach of every rewrite and marker.
    """
    occurrences: list[int] = []
    offset = 0
    table = ""
    for line in text.splitlines(keepends=True):
        header = re.match(r"\[([^\]]+)\]", line.strip())
        if header is not None:
            table = header.group(1)
        elif _DEPENDENCY_TABLES.match(table):
            comment_at = line.find("#")
            searchable = line if comment_at == -1 else line[:comment_at]
            at = searchable.find(quoted)
            if at != -1:
                occurrences.append(offset + at)
        offset += len(line)
    return occurrences


def _classify(requirement: Requirement) -> tuple[str, str] | None:
    """The action for one `mcp` requirement: (kind, message), or None to leave it.

    `rewrite` carries no message; `flag` carries the marker text. Checked in
    trust order -- a removed extra or a URL pin outranks the specifier, since
    rewriting around either would lose something the user wrote deliberately.
    """
    removed = sorted(extra for extra in requirement.extras if extra in REMOVED_EXTRAS)
    if removed:
        return ("flag", f"{REMOVED_EXTRAS[removed[0]]}; set `mcp{V2_SPECIFIER}` by hand")
    if requirement.url is not None:
        return ("flag", "this pins `mcp` by URL: point it at a v2 release by hand")
    if _needs_v2(requirement):
        return ("rewrite", "")
    return None


def _update_pyproject(text: str, *, add_markers: bool) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    parsed: dict[str, object] = tomllib.loads(text)

    for spelled in dict.fromkeys(_pyproject_dependency_strings(parsed)):
        requirement = _mcp_requirement(spelled)
        action = _classify(requirement) if requirement is not None else None
        if requirement is None or action is None:
            continue
        # The TOML string is located by its quoted form; a requirement needing
        # escapes inside a TOML string does not exist in practice.
        quoted = next(
            (q + spelled + q for q in ('"', "'") if _dependency_region_occurrences(text, q + spelled + q)), None
        )
        if quoted is None:
            continue
        kind, message = action
        if kind == "flag":
            at = _dependency_region_occurrences(text, quoted)[0]
            diagnostics.append(Diagnostic(_line_of(text, at), "dependency", "manual", message))
            if add_markers:
                text = _insert_marker_above(text, at, message)
            continue
        replacement = quoted[0] + _rewrite_specifier(spelled) + quoted[0]
        for at in reversed(_dependency_region_occurrences(text, quoted)):
            text = text[:at] + replacement + text[at + len(quoted) :]
            line = _line_of(text, at)
            diagnostics.append(
                Diagnostic(line, "dependency", "info", f"updated the `mcp` requirement to `{V2_SPECIFIER}`")
            )

    if _has_poetry_mcp(parsed):
        message = f"update this Poetry constraint for v2 (`{V2_SPECIFIER}`) by hand"
        # The diagnostic never depends on locating the keys in the text (an inline
        # table defeats the line match); only the marker placement does.
        keys = list(_POETRY_MCP_KEY.finditer(text))
        if not keys:
            diagnostics.append(Diagnostic(1, "dependency", "manual", message))
        for key in reversed(keys):
            diagnostics.append(Diagnostic(_line_of(text, key.start()), "dependency", "manual", message))
            if add_markers:
                text = _insert_marker_above(text, key.start() + len(key.group(0)), message)
    return text, diagnostics


def _update_requirements(text: str, *, add_markers: bool) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    for number, line in enumerate(lines, start=1):
        body = line.split("#", 1)[0]
        spelled = body.strip()
        if not spelled or spelled.startswith("-"):
            out.append(line)
            continue
        requirement = _mcp_requirement(spelled)
        if requirement is None:
            # A line that names mcp but did not parse (a pip-compile
            # continuation, `--hash=` options) may still pin v1; say so.
            if _UNPARSEABLE_MCP_LINE.match(spelled) and _is_unparseable(spelled):
                action = ("flag", f"could not parse this `mcp` line: update it for v2 (`{V2_SPECIFIER}`) by hand")
            else:
                out.append(line)
                continue
        else:
            classified = _classify(requirement)
            if classified is None:
                out.append(line)
                continue
            action = classified
        kind, message = action
        if kind == "flag":
            diagnostics.append(Diagnostic(number, "dependency", "manual", message))
            if add_markers:
                ending = "\r\n" if line.endswith("\r\n") else "\n"
                comment = f"# {MARKER}: {message}{ending}"
                if out[-1:] != [comment]:
                    out.append(comment)
            out.append(line)
            continue
        out.append(line.replace(spelled, _rewrite_specifier(spelled), 1))
        diagnostics.append(
            Diagnostic(number, "dependency", "info", f"updated the `mcp` requirement to `{V2_SPECIFIER}`")
        )
    return "".join(out), diagnostics


def _is_unparseable(spelled: str) -> bool:
    try:
        Requirement(spelled)
    except InvalidRequirement:
        return True
    return False


def _dependency_files(paths: Sequence[Path]) -> Iterator[Path]:
    """Yield every dependency file under the given directories, pruned and sorted."""
    for path in paths:
        if not path.is_dir():
            continue
        found: list[Path] = []
        for directory, child_directories, files in os.walk(path):
            child_directories[:] = [name for name in child_directories if name not in IGNORED_DIRECTORIES]
            found.extend(
                Path(directory, name)
                for name in files
                if name == "pyproject.toml" or (name.startswith("requirements") and name.endswith(".txt"))
            )
        yield from sorted(found)


def update_dependencies(paths: Sequence[Path], *, write: bool, add_markers: bool = True) -> list[DependencyReport]:
    """Update the `mcp` requirement in every dependency file under `paths`.

    Files are read and written as UTF-8 bytes, like the source runner. A file
    that cannot be read or parsed is reported with its error and left as found.
    """
    reports: list[DependencyReport] = []
    for path in _dependency_files(paths):
        source = ""
        try:
            source = path.read_bytes().decode("utf-8")
            if path.name == "pyproject.toml":
                updated, diagnostics = _update_pyproject(source, add_markers=add_markers)
            else:
                updated, diagnostics = _update_requirements(source, add_markers=add_markers)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            reports.append(DependencyReport(path, source, None, [], f"{type(exc).__name__}: {exc}"))
            continue
        if not diagnostics and updated == source:
            continue
        report = DependencyReport(path, source, updated, diagnostics, None)
        if write and report.changed:
            path.write_bytes(updated.encode("utf-8"))
        reports.append(report)
    return reports
