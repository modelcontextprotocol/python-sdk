"""Generate the API reference pages and nav for a Zensical build.

Zensical has no plugin API, so the mkdocs-gen-files + mkdocs-literate-nav
pipeline (docs/hooks/gen_ref_pages.py) is replaced by this pre-build script:

1. Writes one real ``::: dotted.module`` stub page per Python module into
   ``docs/api/`` (same ``__init__`` → ``index.md`` and skip-underscore rules
   as the hook it replaces).
2. Emits ``mkdocs.zensical.yml`` from ``mkdocs.yml``, replacing the
   literate-nav ``- API Reference: api/`` entry with an explicit nested nav
   subtree generated from the module tree, and patching the config keys
   Zensical cannot parse.

Run from the repo root before ``zensical build``:

    uv run --frozen python scripts/gen_api_pages.py
    uv run --frozen zensical build --strict -f mkdocs.zensical.yml

Caveats of the emitted config:

- Zensical silently ignores the carried-over ``hooks:`` entry and the
  ``gen-files``/``literate-nav``/``social`` plugin entries, so the Zensical
  site ships WITHOUT ``llms.txt``/``llms-full.txt`` (docs/hooks/llms_txt.py
  never runs). ``--strict`` does not warn about any of this.
- The real files under ``docs/api/`` are only cleaned by re-running this
  script. A stale page for a since-deleted module fails the strict *mkdocs*
  build; run ``rm -rf docs/api mkdocs.zensical.yml`` before returning to the
  plain mkdocs pipeline.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Maps a module name to its doc path, or a subpackage to its own NavTree
# (whose "__index__" key holds the package's own page).
NavTree = dict[str, "str | NavTree"]

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
API_DIR = ROOT / "docs" / "api"

# `src/mcp-types` is a distribution directory, not an import package, so each
# package's dotted module path is taken relative to its own parent: deriving it
# from `src/` would emit the unimportable `mcp-types.mcp_types.*`.
PACKAGES = (SRC / "mcp", SRC / "mcp-types" / "mcp_types")


def build_tree() -> NavTree:
    """Write one stub page per module into docs/api/ and collect them as a NavTree."""
    tree: NavTree = {}
    for package in PACKAGES:
        base = package.parent
        for path in sorted(package.rglob("*.py")):
            parts = path.relative_to(base).with_suffix("").parts

            if parts[-1] == "__init__":
                parts = parts[:-1]
                doc_path = Path(*parts, "index.md")
                keys = (*parts, "__index__")
            elif parts[-1].startswith("_"):
                continue
            else:
                doc_path = Path(*parts).with_suffix(".md")
                keys = parts

            full_doc_path = API_DIR / doc_path
            full_doc_path.parent.mkdir(parents=True, exist_ok=True)
            full_doc_path.write_text(f"::: {'.'.join(parts)}\n", encoding="utf-8")

            node = tree
            for part in keys[:-1]:
                subtree = node.setdefault(part, {})
                assert isinstance(subtree, dict), f"module/package name collision at {part!r}"
                node = subtree
            node[keys[-1]] = f"api/{doc_path.as_posix()}"
    return tree


def tree_to_nav(tree: NavTree, indent: str) -> list[str]:
    """Render the module tree as mkdocs.yml nav lines (4-space indent per level).

    Names are quoted so YAML-1.1 boolean lookalikes (``on``, ``no``, ...) stay strings.
    """
    lines: list[str] = []
    if "__index__" in tree:
        lines.append(f"{indent}- {tree['__index__']}")
    for name, value in tree.items():
        if name == "__index__":
            continue
        if isinstance(value, str):
            lines.append(f'{indent}- "{name}": {value}')
        else:
            lines.append(f'{indent}- "{name}":')
            lines.extend(tree_to_nav(value, indent + "    "))
    return lines


def replace_once(config: str, old: str, new: str) -> str:
    """Replace an anchor that must appear exactly once, failing loudly if absent.

    A plain ``str.replace`` silently no-ops when mkdocs.yml drifts, emitting a
    config that still holds the unresolvable literate-nav entry or ``!relative``
    tag — the build would then be quietly wrong or fail far from the cause.
    """
    if config.count(old) != 1:
        raise SystemExit(f"expected exactly one occurrence in mkdocs.yml: {old!r}")
    return config.replace(old, new)


def main() -> None:
    if API_DIR.exists():
        shutil.rmtree(API_DIR)
    tree = build_tree()

    nav_lines = tree_to_nav(tree, "      ")
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    # literate-nav directory entry -> explicit generated subtree
    config = replace_once(
        config,
        "  - API Reference: api/\n",
        "  - API Reference:\n" + "\n".join(nav_lines) + "\n",
    )
    # Zensical's YAML loader has no `!relative` constructor. It resolves
    # snippet base paths against the config file's directory, so "." keeps
    # the `docs_src/...` includes anchored at the repo root.
    config = replace_once(
        config,
        "      base_path: !relative $config_dir\n",
        '      base_path: "."\n',
    )

    (ROOT / "mkdocs.zensical.yml").write_text(config, encoding="utf-8")


if __name__ == "__main__":
    main()
