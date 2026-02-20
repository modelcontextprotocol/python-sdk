#!/usr/bin/env python3
"""Sync code snippets from example files into docstrings and markdown.

This script finds snippet-source markers in Python source files and markdown
files, and replaces the content between them with code from the referenced
example files.

Supported target files:
- Python source files under src/ (docstring code examples)
- Markdown files under docs/
- README*.md files at the repo root

Marker format (same in both docstrings and markdown):

    <!-- snippet-source path/to/example.py -->
    ```python
    # content replaced by script
    ```
    <!-- /snippet-source -->

With region extraction:

    <!-- snippet-source path/to/example.py#region_name -->
    ```python
    # content replaced by script
    ```
    <!-- /snippet-source -->

Path-less region markers (for src/ files only):

    <!-- snippet-source #region_name -->
    ```python
    # content replaced by script
    ```
    <!-- /snippet-source -->

    The companion file path is derived from the target file's location:
    src/mcp/foo/bar.py → examples/snippets/docstrings/mcp/foo/bar.py

The code fence language is inferred from the source file extension.

Region markers in example files:

    # region region_name
    code here
    # endregion region_name

Path resolution:
- All paths are relative to the repository root
- Path-less markers (#region) resolve via: src/X → COMPANION_BASE/X

Usage:
    uv run python scripts/sync_snippets.py          # Sync all snippets
    uv run python scripts/sync_snippets.py --check  # Check mode for CI
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# Pattern to match snippet-source blocks.
# Captures: indent, source path, content between markers.
SNIPPET_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)<!-- snippet-source (?P<source>\S+) -->\n"
    r"(?P<content>.*?)"
    r"^(?P=indent)<!-- /snippet-source -->",
    re.MULTILINE | re.DOTALL,
)

# Region markers in example files.
REGION_START_PATTERN = re.compile(r"^(?P<indent>\s*)# region (?P<name>\S+)\s*$")
REGION_END_PATTERN = re.compile(r"^\s*# endregion (?P<name>\S+)\s*$")

# Base directory for companion example files (relative to repo root).
COMPANION_BASE = Path("examples/snippets/docstrings")

# Source prefix stripped when deriving companion paths.
SOURCE_PREFIX = Path("src")


def find_repo_root() -> Path:
    """Find the repository root by looking for pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find repository root (no pyproject.toml found)")


def resolve_source_path(source_path: str, repo_root: Path) -> Path:
    """Resolve a source path relative to the repository root."""
    return (repo_root / source_path).resolve()


def list_regions(content: str) -> list[str]:
    """List all region names defined in file content."""
    regions: list[str] = []
    for line in content.split("\n"):
        m = REGION_START_PATTERN.match(line)
        if m:
            regions.append(m.group("name"))
    return regions


def extract_region(content: str, region_name: str, file_path: str) -> str:
    """Extract a named region from file content.

    Regions are delimited by:
        # region region_name
        ... code ...
        # endregion region_name

    The extracted content is dedented using textwrap.dedent.
    """
    lines = content.split("\n")

    start_idx = None
    for i, line in enumerate(lines):
        m = REGION_START_PATTERN.match(line)
        if m and m.group("name") == region_name:
            start_idx = i
            break

    if start_idx is None:
        available = list_regions(content)
        available_str = ", ".join(available) if available else "(none)"
        raise ValueError(f"Region '{region_name}' not found in {file_path}. Available regions: {available_str}")

    end_idx = None
    for i in range(start_idx + 1, len(lines)):
        m = REGION_END_PATTERN.match(lines[i])
        if m and m.group("name") == region_name:
            end_idx = i
            break

    if end_idx is None:
        raise ValueError(f"No matching '# endregion {region_name}' found in {file_path}")

    region_lines = lines[start_idx + 1 : end_idx]
    region_content = "\n".join(region_lines)

    return textwrap.dedent(region_content).strip()


@dataclass
class ProcessingResult:
    """Result of processing a single file."""

    file_path: Path
    modified: bool = False
    snippets_processed: int = 0
    errors: list[str] = field(default_factory=lambda: [])


class SnippetSyncer:
    """Syncs code snippets from example files into target files."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._file_cache: dict[str, str] = {}
        self._region_cache: dict[str, str] = {}

    def derive_companion_path(self, target_file: Path) -> str:
        """Derive the companion example file path from a source file path.

        Maps src/mcp/X → examples/snippets/docstrings/mcp/X
        """
        rel = target_file.relative_to(self.repo_root)
        try:
            sub = rel.relative_to(SOURCE_PREFIX)
        except ValueError:
            raise ValueError(
                f"Cannot derive companion path for {rel}: "
                f"path-less #region markers are only supported in {SOURCE_PREFIX}/ files"
            ) from None
        return str(COMPANION_BASE / sub)

    def resolve_source_ref(self, source_ref: str, target_file: Path) -> str:
        """Resolve a source reference, expanding path-less #region markers."""
        if source_ref.startswith("#"):
            companion = self.derive_companion_path(target_file)
            return f"{companion}{source_ref}"
        return source_ref

    def get_file_content(self, resolved_path: Path) -> str:
        """Get file content, using cache."""
        key = str(resolved_path)
        if key not in self._file_cache:
            if not resolved_path.exists():
                raise FileNotFoundError(f"Example file not found: {resolved_path}")
            self._file_cache[key] = resolved_path.read_text()
        return self._file_cache[key]

    def get_source_content(self, source_ref: str) -> str:
        """Get the content for a source reference (path or path#region)."""
        if "#" in source_ref:
            file_path_str, region_name = source_ref.rsplit("#", 1)
        else:
            file_path_str = source_ref
            region_name = None

        resolved = resolve_source_path(file_path_str, self.repo_root)
        file_content = self.get_file_content(resolved)

        if region_name is None:
            return file_content.strip()

        cache_key = f"{resolved}#{region_name}"
        if cache_key not in self._region_cache:
            self._region_cache[cache_key] = extract_region(file_content, region_name, file_path_str)
        return self._region_cache[cache_key]

    def process_file(self, file_path: Path, *, check: bool = False) -> ProcessingResult:
        """Process a single file to sync snippets."""
        result = ProcessingResult(file_path=file_path)

        content = file_path.read_text()
        original_content = content

        def replace_snippet(match: re.Match[str]) -> str:
            indent = match.group("indent")
            source_ref = match.group("source")

            try:
                resolved_ref = self.resolve_source_ref(source_ref, file_path)
                code = self.get_source_content(resolved_ref)
            except (FileNotFoundError, ValueError) as e:
                result.errors.append(f"{file_path}: {e}")
                return match.group(0)

            result.snippets_processed += 1

            # Infer language from file extension
            raw_path = resolved_ref.split("#")[0]
            ext = Path(raw_path).suffix.lstrip(".")
            lang = {"py": "python", "yml": "yaml"}.get(ext, ext)

            # Indent the code to match the marker indentation
            indented_code = textwrap.indent(code, indent)

            # Build replacement block
            lines = [
                f"{indent}<!-- snippet-source {source_ref} -->",
                f"{indent}```{lang}",
                indented_code,
                f"{indent}```",
                f"{indent}<!-- /snippet-source -->",
            ]
            return "\n".join(lines)

        content = SNIPPET_PATTERN.sub(replace_snippet, content)

        if content != original_content:
            result.modified = True
            if not check:
                file_path.write_text(content)

        return result

    def find_target_files(self) -> list[Path]:
        """Find all files that should be scanned for snippet markers."""
        files: list[Path] = []

        # Python source files
        src_dir = self.repo_root / "src"
        if src_dir.exists():
            files.extend(src_dir.rglob("*.py"))

        # Markdown docs
        docs_dir = self.repo_root / "docs"
        if docs_dir.exists():
            files.extend(docs_dir.rglob("*.md"))

        # TODO(v2): Change to README.md when v2 is released.
        readme = self.repo_root / "README.v2.md"
        if readme.exists():
            files.append(readme)

        return sorted(files)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync code snippets from example files")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode - verify snippets are up to date without modifying",
    )
    args = parser.parse_args()

    repo_root = find_repo_root()
    syncer = SnippetSyncer(repo_root)

    if args.check:
        print("Checking code snippets are in sync...\n")
    else:
        print("Syncing code snippets from example files...\n")

    files = syncer.find_target_files()
    results = [syncer.process_file(f, check=args.check) for f in files]

    # Report
    modified = [r for r in results if r.modified]
    all_errors: list[str] = []
    for r in results:
        all_errors.extend(r.errors)

    if modified:
        if args.check:
            print(f"{len(modified)} file(s) out of sync:")
        else:
            print(f"Modified {len(modified)} file(s):")
        for r in modified:
            print(f"  {r.file_path} ({r.snippets_processed} snippet(s))")
    else:
        print("All snippets are up to date")

    if all_errors:
        print("\nErrors:")
        for error in all_errors:
            print(f"  {error}")
        sys.exit(2)

    if args.check and modified:
        print("\nRun 'uv run python scripts/sync_snippets.py' to fix.")
        sys.exit(1)

    print("\nSnippet sync complete!")


if __name__ == "__main__":
    main()
