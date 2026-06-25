"""mcp-types is installable without the mcp SDK.

`mcp_types` may import only the standard library and what
`src/mcp-types/pyproject.toml` declares: `pydantic` and `typing-extensions`.
The check reads every module's imports from source rather than executing
them, so lazy and `TYPE_CHECKING`-only imports are held to the same bar.
"""

import ast
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parent.parent.parent / "src" / "mcp-types" / "mcp_types"

ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {
    # Relative imports resolve inside the package; `_imported_roots` maps them to "".
    "",
    "mcp_types",
    # The two dependencies `src/mcp-types/pyproject.toml` declares.
    "pydantic",
    "typing_extensions",
}


def _imported_roots(module: Path) -> set[str]:
    """Top-level package named by each import statement in `module`."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"), filename=str(module))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `from .x import y` normalizes to "" via the leading-dot prefix.
            roots.add(("." * node.level + (node.module or "")).partition(".")[0])
    return roots


def test_mcp_types_imports_only_its_declared_dependencies() -> None:
    """Every import in every mcp_types module names the standard library, a
    declared dependency, or mcp_types itself — never the mcp SDK."""
    modules = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert {module.stem for module in modules} >= {"methods", "jsonrpc", "version"}
    imported: set[str] = set()
    for module in modules:
        imported |= _imported_roots(module)
    assert imported - ALLOWED_ROOTS == set()
