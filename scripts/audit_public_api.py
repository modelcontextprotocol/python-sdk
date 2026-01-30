"""Audit the public API surface of the mcp package.

Identifies three categories of issues:
  1. Leaked modules — implementation .py files without a _ prefix that are
     directly importable but not gated by any __init__.py __all__.
  2. Missing __all__ — non-empty __init__.py files that lack an __all__,
     meaning their public surface is uncontrolled.
  3. Declared public surface — the union of every name in every __all__,
     with its fully-qualified import path.

Usage:
    uv run python scripts/audit_public_api.py

Exit codes:
    0  No issues found, surface matches allowlist (if provided)
    1  Issues found or surface drift detected
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def parse_all(file: Path) -> list[str] | None:
    """Parse the __all__ list from a Python file.  Returns None if absent."""
    tree = ast.parse(file.read_text(), filename=str(file))
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    return [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
                # __all__ is assigned but not a literal list — can't parse statically
                return None
    return None


# ---------------------------------------------------------------------------
# Walk the package tree
# ---------------------------------------------------------------------------

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
PKG_ROOT = SRC_ROOT / "mcp"


def leaked_modules() -> list[str]:
    """Implementation .py files without _ prefix (directly importable)."""
    results: list[str] = []
    for py_file in sorted(PKG_ROOT.rglob("*.py")):
        if py_file.name in ("__init__.py", "__main__.py"):
            continue
        if py_file.name.startswith("_"):
            continue
        rel = py_file.relative_to(SRC_ROOT)
        module_path = str(rel.with_suffix("")).replace("/", ".")
        results.append(module_path)
    return results


def missing_all() -> list[str]:
    """__init__.py files that are non-empty but have no __all__."""
    results: list[str] = []
    for init in sorted(PKG_ROOT.rglob("__init__.py")):
        text = init.read_text().strip()
        if not text:
            continue
        if parse_all(init) is None:
            rel = init.relative_to(SRC_ROOT)
            results.append(str(rel))
    return results


def declared_surface() -> list[str]:
    """Every name declared in an __all__, fully qualified."""
    entries: list[str] = []
    for init in sorted(PKG_ROOT.rglob("__init__.py")):
        names = parse_all(init)
        if not names:
            continue
        rel = init.relative_to(SRC_ROOT)
        # e.g. mcp/client/__init__.py -> mcp.client
        pkg = str(rel.parent).replace("/", ".")
        for name in sorted(names):
            entries.append(f"{pkg}.{name}")
    return entries


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

SEPARATOR = "-" * 70


def main() -> int:
    issues = 0

    # --- Leaked modules ---
    leaked = leaked_modules()
    print(f"\n{'LEAKED IMPLEMENTATION MODULES':^70}")
    print("(files importable by name — should be renamed to _module.py)")
    print(SEPARATOR)
    if leaked:
        for mod in leaked:
            print(f"  {mod}")
        print(f"\n  Total: {len(leaked)}")
        issues += len(leaked)
    else:
        print("  ✓ None")
    print()

    # --- Missing __all__ ---
    missing = missing_all()
    print(f"{'__init__.py FILES MISSING __all__':^70}")
    print("(package boundaries without explicit export control)")
    print(SEPARATOR)
    if missing:
        for f in missing:
            print(f"  {f}")
        print(f"\n  Total: {len(missing)}")
        issues += len(missing)
    else:
        print("  ✓ None")
    print()

    # --- Declared surface ---
    surface = declared_surface()
    print(f"{'DECLARED PUBLIC SURFACE':^70}")
    print("(union of all __all__ declarations)")
    print(SEPARATOR)
    for entry in surface:
        print(f"  {entry}")
    print(f"\n  Total: {len(surface)} public names\n")

    # --- Allowlist comparison ---
    allowlist_path = PKG_ROOT.parent.parent / "docs" / "public_api_allowlist.txt"
    if allowlist_path.exists():
        allowlisted = {
            line.strip()
            for line in allowlist_path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        actual = set(surface)

        added = sorted(actual - allowlisted)
        removed = sorted(allowlisted - actual)

        print(f"{'ALLOWLIST COMPARISON':^70}")
        print(SEPARATOR)
        if added:
            print("  NEW (not in allowlist):")
            for name in added:
                print(f"    + {name}")
            issues += len(added)
        if removed:
            print("  REMOVED (in allowlist but not exported):")
            for name in removed:
                print(f"    - {name}")
            issues += len(removed)
        if not added and not removed:
            print("  ✓ Surface matches allowlist exactly")
        print()

    if issues:
        print(f"  {issues} issue(s) found.")
        return 1

    print("  All clear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
