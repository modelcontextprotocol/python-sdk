"""Diff two uv.lock files for the dependency canary report.

Usage: python scripts/ci/canary_lock_diff.py OLD NEW [--old-label L] [--new-label L] [--suspects FILE]

Prints a Markdown table of every package whose locked version(s) differ between
OLD and NEW, tagged by its role relative to the root `mcp` package: a direct
runtime dependency, a transitive runtime dependency (reachable from `mcp` with
all extras, ignoring markers), or tooling (only reachable through a dependency
group). Prints nothing when the two locks agree. With --suspects, also writes a
one-line summary of the changed runtime dependencies (direct first) to FILE,
for use in an issue title.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import tomllib

Package = dict[str, Any]

ROOT = "mcp"


def load(path: Path) -> list[Package]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("package", [])


def versions(packages: list[Package]) -> dict[str, list[str]]:
    """name -> sorted distinct versions (a name can be locked more than once across marker forks)."""
    out: dict[str, set[str]] = {}
    for pkg in packages:
        if "version" in pkg and "editable" not in pkg.get("source", {}) and "virtual" not in pkg.get("source", {}):
            out.setdefault(pkg["name"], set()).add(pkg["version"])
    return {name: sorted(vs) for name, vs in out.items()}


def runtime_roles(packages: list[Package]) -> tuple[set[str], set[str]]:
    """(direct, closure): names mcp depends on directly (any extra), and everything reachable from them."""
    by_name: dict[str, list[Package]] = {}
    for pkg in packages:
        by_name.setdefault(pkg["name"], []).append(pkg)

    def edges(name: str, extras: frozenset[str]) -> list[tuple[str, frozenset[str]]]:
        found: list[tuple[str, frozenset[str]]] = []
        for pkg in by_name.get(name, []):
            deps = list(pkg.get("dependencies", []))
            for extra in extras:
                deps += pkg.get("optional-dependencies", {}).get(extra, [])
            found += [(d["name"], frozenset(d.get("extra", []))) for d in deps]
        return found

    root_extras = frozenset().union(*(pkg.get("optional-dependencies", {}).keys() for pkg in by_name.get(ROOT, [])))
    direct = {name for name, _ in edges(ROOT, root_extras)}
    closure: set[str] = set()
    seen: set[tuple[str, frozenset[str]]] = set()
    todo = [(ROOT, root_extras)]
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        closure.add(node[0])
        todo += edges(*node)
    closure.discard(ROOT)
    return direct, closure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--old-label", default="before")
    parser.add_argument("--new-label", default="after")
    parser.add_argument("--suspects", type=Path, help="write a one-line title summary of changed runtime deps here")
    args = parser.parse_args()

    old_packages, new_packages = load(args.old), load(args.new)
    old, new = versions(old_packages), versions(new_packages)
    # Union of both locks' graphs, so a dependency dropped by the new resolution keeps its old role.
    direct, closure = (a | b for a, b in zip(runtime_roles(old_packages), runtime_roles(new_packages)))

    def role(name: str) -> tuple[int, str]:
        if name in direct:
            return 0, "runtime (direct)"
        if name in closure:
            return 1, "runtime (transitive)"
        return 2, "tooling"

    changed = sorted((role(n), n) for n in old.keys() | new.keys() if old.get(n) != new.get(n))
    # Tooling that merely appears or disappears (e.g. a dependency group stripped before resolving) is noise here.
    changed = [c for c in changed if c[0][0] < 2 or (c[1] in old and c[1] in new)]
    if changed:
        print(f"| Package | {args.old_label} | {args.new_label} | Role |")
        print("| --- | --- | --- | --- |")
        for (_, label), name in changed:
            before = ", ".join(old.get(name, [])) or "(absent)"
            after = ", ".join(new.get(name, [])) or "(removed)"
            print(f"| {name} | {before} | {after} | {label} |")

    if args.suspects:
        runtime = [f"{n} {new[n][-1]}" for (rank, _), n in changed if rank < 2 and n in new]
        summary = ", ".join(runtime[:3]) + (f" (+{len(runtime) - 3} more)" if len(runtime) > 3 else "")
        args.suspects.write_text(summary + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
