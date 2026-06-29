"""Structural invariants every `docs_src/` example must satisfy.

These are deliberately string/regex checks, not an AST analyzer: each predicate
is branch-free at the call site so the suite stays compatible with the repo's
100% branch-coverage gate, and a contributor whose doc PR goes red gets a
one-line reason, not a parser traceback.
"""

import importlib
import re
from itertools import filterfalse
from pathlib import Path

import pytest

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")

REPO_ROOT = Path(__file__).parent.parent.parent
DOCS_SRC = REPO_ROOT / "docs_src"

EXAMPLE_FILES = sorted(p for p in DOCS_SRC.rglob("*.py") if p.name != "__init__.py")
"""Every example module under `docs_src/` (the `__init__.py` scaffolding is not an example)."""

_PRIVATE_MCP_IMPORT = re.compile(r"^\s*(?:from|import)\s+(mcp(?:\.\w+)*\._\w+)", re.MULTILINE)
"""A `_`-private segment inside the imported MODULE path: `from mcp.client._memory import X`."""

_PRIVATE_MCP_NAME = re.compile(r"^\s*from\s+(mcp(?:\.\w+)*)\s+import\s+[^#\n]*?\b(_\w+)\b", re.MULTILINE)
"""A `_`-private NAME imported from a public `mcp` module: `from mcp.client import _memory`."""

RETIRED_NAMES = ("UrlElicitationRequiredError",)
"""Public SDK names built on protocol surfaces retired by the 2026-07-28 spec.

`UrlElicitationRequiredError` is the `-32042` flow; the spec lists that code as
reserved-never-reused, so no documentation example may teach it even while the
symbol is still exported.
"""

_INCLUDE_DIRECTIVE = re.compile(r"(?:--8<--\s*\"|<!-- snippet-source\s+)(docs_src/[^\s\"]+)")
"""A `--8<-- "docs_src/..."` mkdocs include or a `<!-- snippet-source docs_src/... -->` README marker."""


def _rel(path: Path) -> str:
    """A repo-relative path, used as the parametrize id so failures name the file."""
    return path.relative_to(REPO_ROOT).as_posix()


def _module_name(path: Path) -> str:
    """The dotted import name of an example, derived from its repo-relative path."""
    return _rel(path).removesuffix(".py").replace("/", ".")


def _private_mcp_imports(source: str) -> list[str]:
    """Every `mcp.*` import in `source` that reaches a `_`-private module OR name.

    Two single-line spellings are covered: a private segment in the module path
    (`from mcp.client._memory import X`, `import mcp.server._otel`) and a private
    name pulled from a public module (`from mcp.client import _memory`).
    """
    named = [f"{module}.{name}" for module, name in _PRIVATE_MCP_NAME.findall(source)]
    return _PRIVATE_MCP_IMPORT.findall(source) + named


def _retired_names_used(source: str) -> list[str]:
    """The retired SDK names that appear anywhere in `source`."""
    return [name for name in RETIRED_NAMES if name in source]


def _referenced_examples() -> set[str]:
    """Every `docs_src/...` path that some docs page or the README actually includes.

    The README is globbed rather than named so this survives the planned
    `README.v2.md` -> `README.md` rename instead of crashing on a missing file.
    """
    pages = [*sorted((REPO_ROOT / "docs").rglob("*.md")), *sorted(REPO_ROOT.glob("README*.md"))]
    return {ref for page in pages for ref in _INCLUDE_DIRECTIVE.findall(page.read_text(encoding="utf-8"))}


def _is_real_file(rel: str) -> bool:
    """Whether a repo-relative path exists on disk."""
    return (REPO_ROOT / rel).is_file()


def test_private_mcp_import_detector() -> None:
    """The detector flags both single-line spellings of a private `mcp` reach-in, and only those.

    It does not parse Python: a private name hidden behind an `as` alias or inside a
    parenthesised multi-line `import` would slip through. Examples are short single-line
    imports, so the cheap detector is the right trade against a 100-line AST analyzer.
    """
    assert _private_mcp_imports("from mcp.client._memory import InMemoryTransport") == ["mcp.client._memory"]
    assert _private_mcp_imports("import mcp.server._otel") == ["mcp.server._otel"]
    assert _private_mcp_imports("from mcp.client import _memory") == ["mcp.client._memory"]
    assert _private_mcp_imports("from mcp.server import MCPServer\nfrom mcp.client.client import Client") == []
    # only `mcp` is policed: another library's private module is not this test's business
    assert _private_mcp_imports("from pydantic._internal import _fields") == []


def test_retired_name_detector() -> None:
    """The detector flags a retired name and stays quiet on clean source."""
    assert _retired_names_used("raise UrlElicitationRequiredError([])") == ["UrlElicitationRequiredError"]
    assert _retired_names_used("from mcp.server import MCPServer") == []


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_rel)
def test_example_imports(path: Path) -> None:
    """The example imports cleanly against the current SDK.

    A renamed symbol, a moved import path, or a changed keyword argument breaks an
    example at import time, long before anyone reads the page it appears on.

    Honest scope: an example another test in this directory already imported is a
    `sys.modules` cache hit here and its real coverage is that behavioural test.
    This test is the floor for the example that has a page but no test yet.
    """
    importlib.import_module(_module_name(path))


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_rel)
def test_example_uses_only_public_mcp_modules(path: Path) -> None:
    """An example is the public API contract: it must never import a `_`-private `mcp` module."""
    assert not _private_mcp_imports(path.read_text(encoding="utf-8")), f"{_rel(path)} reaches into private mcp"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_rel)
def test_example_avoids_retired_api(path: Path) -> None:
    """An example must not teach an API the 2026-07-28 spec retired, even while it is still exported."""
    assert not _retired_names_used(path.read_text(encoding="utf-8")), f"{_rel(path)} uses a retired API"


def test_every_example_is_included_by_a_page() -> None:
    """Every `docs_src/` example is shown by at least one docs page or the README.

    An orphan example is dead documentation: it gets type-checked and tested
    but no reader ever sees it, so it silently stops describing anything.
    """
    examples = {_rel(p) for p in EXAMPLE_FILES}
    orphans = sorted(examples - _referenced_examples())
    assert not orphans, f"docs_src files no page includes: {orphans}"


def test_every_included_path_exists() -> None:
    """Every `docs_src/` path a page includes exists on disk.

    `mkdocs build --strict` also enforces this, but only when the docs are
    built; this puts the same guarantee inside the ordinary `pytest` run.
    """
    missing = sorted(filterfalse(_is_real_file, _referenced_examples()))
    assert not missing, f"pages include docs_src files that do not exist: {missing}"
