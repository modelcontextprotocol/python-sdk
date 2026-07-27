"""AST shape-check: stories keep the SDK construction visible and the harness contained.

The python analogue of typescript-sdk's eslint import-allowlist over its examples,
strictly stronger: it also asserts each ``main`` constructs ``Client(...)`` itself —
the regression the harness inversion exists to prevent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.examples.conftest import STORIES, STORIES_DIR, story_cfg

_HARNESS_ALLOWLIST = frozenset({"run_client", "target_from_args", "Target", "TargetFactory"})
"""The only ``stories._harness`` names a ``client.py`` may use. ``AuthBuilder`` is
additionally allowed in a ``client.py`` that defines ``build_auth`` (the auth seam
``run_client`` and the conftest both look up by name)."""

_MCPSERVER_TIER = ("mcp.server.mcpserver", "mcp.server.MCPServer")
"""Both spellings of the high-level tier: the ``mcpserver`` module and its ``mcp.server`` re-export."""

_LOWLEVEL_STORIES = [name for name in sorted(STORIES) if story_cfg(name)["lowlevel"]]


def _parse(path: Path) -> ast.Module:
    """Parse ``path`` into an AST module."""
    return ast.parse(path.read_text(), filename=str(path))


def _resolve(node: ast.ImportFrom, package: str) -> str:
    """The absolute module path ``node`` imports from, resolving a relative import against ``package``."""
    parents = package.split(".")[: -(node.level - 1) or None] if node.level else []
    return ".".join([*parents, *([node.module] if node.module else [])])


def _module_paths(tree: ast.Module, package: str) -> set[str]:
    """Every dotted module path the file (a module in ``package``) references — imports, with relative
    ones resolved to absolute, plus attribute chains rooted at an import-bound name (``import mcp.shared``
    + ``mcp.shared._memory.f()``), so a reach-in is caught however it is spelled."""
    paths: set[str] = set()
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                paths.add(alias.name)
                local = alias.asname or alias.name.partition(".")[0]
                bound[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            module = _resolve(node, package)
            for alias in node.names:
                paths.add(f"{module}.{alias.name}")
                bound[alias.asname or alias.name] = f"{module}.{alias.name}"
    for node in ast.walk(tree):
        attrs: list[str] = []
        expr: ast.AST = node
        while isinstance(expr, ast.Attribute):
            attrs.append(expr.attr)
            expr = expr.value
        if attrs and isinstance(expr, ast.Name) and expr.id in bound:
            paths.add(".".join([bound[expr.id], *reversed(attrs)]))
    return paths


def _is_private_mcp(path: str) -> bool:
    """True when ``path`` crosses a ``_``-private segment inside the ``mcp`` package."""
    head, *rest = path.split(".")
    return head == "mcp" and any(part.startswith("_") for part in rest)


def _is_story_module(path: str) -> bool:
    """True for ``stories.<story>...`` — a story package, not a ``stories._*`` scaffold."""
    head, _, rest = path.partition(".")
    return head == "stories" and bool(rest) and not rest.startswith("_")


@pytest.mark.parametrize("name", sorted(STORIES))
def test_main_constructs_client_inline(name: str) -> None:
    """``main``'s body contains a literal ``Client(...)`` call; the construction is never hidden in a helper."""
    tree = _parse(STORIES_DIR / name / "client.py")
    mains = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main"]
    assert mains, f"{name}/client.py defines no top-level async `main`"
    calls = {n.func.id for n in ast.walk(mains[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "Client" in calls, f"{name}/client.py: main() never calls Client(...) itself"


@pytest.mark.parametrize("name", sorted(STORIES))
def test_client_harness_imports_within_allowlist(name: str) -> None:
    """``client.py`` takes nothing from ``stories._harness`` beyond the allowlist, bounding the harness surface."""
    tree = _parse(STORIES_DIR / name / "client.py")
    defines_build_auth = any(isinstance(n, ast.FunctionDef) and n.name == "build_auth" for n in tree.body)
    allowed = _HARNESS_ALLOWLIST | {"AuthBuilder"} if defines_build_auth else _HARNESS_ALLOWLIST
    paths = _module_paths(tree, package=f"stories.{name}")
    used = {p.removeprefix("stories._harness.").partition(".")[0] for p in paths if p.startswith("stories._harness.")}
    assert used <= allowed, f"{name}/client.py uses {sorted(used - allowed)} from stories._harness"


@pytest.mark.parametrize("name", sorted(STORIES))
def test_story_files_import_no_private_mcp_module(name: str) -> None:
    """No file in a story directory references a ``_``-private ``mcp.*`` module."""
    for path in sorted((STORIES_DIR / name).glob("*.py")):
        private = sorted(p for p in _module_paths(_parse(path), package=f"stories.{name}") if _is_private_mcp(p))
        assert not private, f"{path.relative_to(STORIES_DIR)} reaches into private mcp module(s): {private}"


@pytest.mark.parametrize("name", _LOWLEVEL_STORIES)
def test_server_lowlevel_imports_no_mcpserver_tier(name: str) -> None:
    """``server_lowlevel.py`` stays on the lowlevel tier; it never references ``MCPServer`` or its module."""
    paths = _module_paths(_parse(STORIES_DIR / name / "server_lowlevel.py"), package=f"stories.{name}")
    high = sorted(p for p in paths if any(f"{p}.".startswith(f"{tier}.") for tier in _MCPSERVER_TIER))
    assert not high, f"{name}/server_lowlevel.py references the MCPServer tier: {high}"


@pytest.mark.parametrize("scaffold", ["_harness.py", "_hosting.py"])
def test_scaffold_imports_no_story_module(scaffold: str) -> None:
    """The dependency is one-way: ``_harness.py`` / ``_hosting.py`` import no ``stories.<story>`` module."""
    story_refs = sorted(
        p for p in _module_paths(_parse(STORIES_DIR / scaffold), package="stories") if _is_story_module(p)
    )
    assert not story_refs, f"{scaffold} imports a story module: {story_refs}"
