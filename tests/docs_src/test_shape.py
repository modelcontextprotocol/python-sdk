"""Structural invariants every `docs_src/` example must satisfy.

Deliberately string/regex checks, not an AST analyzer: branch-free predicates keep the
repo's 100% branch-coverage gate happy, and a failing doc PR gets a one-line reason,
not a parser traceback.
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

_PRIVATE_MCP_IMPORT = re.compile(r"^\s*(?:from|import)\s+(mcp(?:\.\w+)*\._\w+)", re.MULTILINE)
"""A `_`-private segment inside the imported MODULE path: `from mcp.client._memory import X`."""

_PRIVATE_MCP_NAME = re.compile(r"^\s*from\s+(mcp(?:\.\w+)*)\s+import\s+[^#\n]*?\b(_\w+)\b", re.MULTILINE)
"""A `_`-private NAME imported from a public `mcp` module: `from mcp.client import _memory`."""

RETIRED_NAMES = ("UrlElicitationRequiredError",)
"""Still-exported SDK names built on surfaces the 2026-07-28 spec retired.

`-32042` is reserved-never-reused, so no example may teach the `UrlElicitationRequiredError` flow.
"""

_INCLUDE_DIRECTIVE = re.compile(r"(?:--8<--\s*\"|<!-- snippet-source\s+)(docs_src/[^\s\"]+)")
"""A `--8<-- "docs_src/..."` mkdocs include or a `<!-- snippet-source docs_src/... -->` README marker."""


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _module_name(path: Path) -> str:
    return _rel(path).removesuffix(".py").replace("/", ".")


def _private_mcp_imports(source: str) -> list[str]:
    """Every `mcp.*` import in `source` that reaches a `_`-private module or name."""
    named = [f"{module}.{name}" for module, name in _PRIVATE_MCP_NAME.findall(source)]
    return _PRIVATE_MCP_IMPORT.findall(source) + named


def _retired_names_used(source: str) -> list[str]:
    return [name for name in RETIRED_NAMES if name in source]


def _referenced_examples() -> set[str]:
    pages = [*sorted((REPO_ROOT / "docs").rglob("*.md")), REPO_ROOT / "README.md"]
    return {ref for page in pages for ref in _INCLUDE_DIRECTIVE.findall(page.read_text(encoding="utf-8"))}


def _is_real_file(rel: str) -> bool:
    return (REPO_ROOT / rel).is_file()


def test_private_mcp_import_detector() -> None:
    """Both single-line spellings are flagged, and only those.

    An `as` alias or a parenthesised multi-line import slips through by design —
    examples use short single-line imports.
    """
    assert _private_mcp_imports("from mcp.client._memory import InMemoryTransport") == ["mcp.client._memory"]
    assert _private_mcp_imports("import mcp.server._otel") == ["mcp.server._otel"]
    assert _private_mcp_imports("from mcp.client import _memory") == ["mcp.client._memory"]
    assert _private_mcp_imports("from mcp.server import MCPServer\nfrom mcp.client.client import Client") == []
    # only `mcp` is policed: another library's private module is not this test's business
    assert _private_mcp_imports("from pydantic._internal import _fields") == []


def test_retired_name_detector() -> None:
    assert _retired_names_used("raise UrlElicitationRequiredError([])") == ["UrlElicitationRequiredError"]
    assert _retired_names_used("from mcp.server import MCPServer") == []


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_rel)
def test_example_imports(path: Path) -> None:
    """The example imports cleanly against the current SDK.

    An example another test here already imported is a `sys.modules` cache hit and its real
    coverage is that behavioural test; this is the floor for examples with no test yet.
    """
    importlib.import_module(_module_name(path))


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_rel)
def test_example_uses_only_public_mcp_modules(path: Path) -> None:
    """An example is the public API contract: it must never import a `_`-private `mcp` module."""
    assert not _private_mcp_imports(path.read_text(encoding="utf-8")), f"{_rel(path)} reaches into private mcp"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_rel)
def test_example_avoids_retired_api(path: Path) -> None:
    assert not _retired_names_used(path.read_text(encoding="utf-8")), f"{_rel(path)} uses a retired API"


def test_every_example_is_included_by_a_page() -> None:
    """An orphan example is dead documentation: type-checked and tested but never seen by a reader."""
    examples = {_rel(p) for p in EXAMPLE_FILES}
    orphans = sorted(examples - _referenced_examples())
    assert not orphans, f"docs_src files no page includes: {orphans}"


def test_every_included_path_exists() -> None:
    """`mkdocs build --strict` enforces this too, but only at docs build; this puts it in plain `pytest`."""
    missing = sorted(filterfalse(_is_real_file, _referenced_examples()))
    assert not missing, f"pages include docs_src files that do not exist: {missing}"
