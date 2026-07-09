"""Generate the API reference pages and navigation.

Zensical does not run MkDocs plugins, so the work that ``mkdocs-gen-files`` and
``mkdocs-literate-nav`` used to do at build time happens here as a plain
pre-build step: this module writes a mkdocstrings stub (``::: <module>``) for
every public module under ``docs/api/`` and returns the matching nested
navigation, which ``scripts/docs/build_config.py`` splices into the build config.

Run as a script it just (re)generates ``docs/api/``; imported, :func:`generate`
also returns the nav so the config builder can consume it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# A MkDocs/Zensical nav is a list of entries, each either ``{title: url}`` for a
# page or ``{title: [children]}`` for a section (a bare ``url`` string attaches
# a section index page, courtesy of the ``navigation.indexes`` feature).
NavItem = "str | dict[str, str | list[NavItem]]"

ROOT = Path(__file__).parent.parent.parent
API_DIR = ROOT / "docs" / "api"


class _Node:
    """A module (``url``) and/or a package with child modules (``children``)."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.children: dict[str, _Node] = {}

    def child(self, name: str) -> _Node:
        return self.children.setdefault(name, _Node())

    def to_nav(self, title: str) -> NavItem:
        if not self.children:
            assert self.url is not None
            return {title: self.url}
        items: list[NavItem] = []
        if self.url is not None:
            items.append(self.url)
        items.extend(self.children[name].to_nav(name) for name in sorted(self.children))
        return {title: items}


def generate() -> list[NavItem]:
    """Write ``docs/api/**.md`` stubs and return the API-section navigation."""
    if API_DIR.exists():
        shutil.rmtree(API_DIR)

    src = ROOT / "src"
    root = _Node()

    # `src/mcp-types` is a distribution directory, not an import package, so each
    # package's dotted module path is taken relative to its own parent: deriving
    # it from `src/` would emit the unimportable `mcp-types.mcp_types.*`.
    for package in (src / "mcp", src / "mcp-types" / "mcp_types"):
        base = package.parent
        for path in sorted(package.rglob("*.py")):
            module_path = path.relative_to(base).with_suffix("")
            doc_path = path.relative_to(base).with_suffix(".md")

            parts = tuple(module_path.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
                doc_path = doc_path.with_name("index.md")
            elif parts[-1].startswith("_"):
                continue

            full_doc_path = API_DIR / doc_path
            full_doc_path.parent.mkdir(parents=True, exist_ok=True)
            ident = ".".join(parts)
            full_doc_path.write_text(f"::: {ident}\n", encoding="utf-8")

            node = root
            for part in parts:
                node = node.child(part)
            node.url = f"api/{doc_path.as_posix()}"

    return [root.children[name].to_nav(name) for name in sorted(root.children)]


if __name__ == "__main__":
    generate()
