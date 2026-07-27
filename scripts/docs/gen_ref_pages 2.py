"""Generate the API reference pages and navigation.

Zensical does not run MkDocs plugins, so the work that `mkdocs-gen-files` and
`mkdocs-literate-nav` used to do at build time happens here as a plain
pre-build step: this module writes a mkdocstrings stub (`::: <module>`) for
every public module under `docs/api/` and returns the matching nested
navigation, which `scripts/docs/build_config.py` splices into the build config.

Run as a script it just (re)generates `docs/api/`; imported, `generate`
also returns the nav so the config builder can consume it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import griffe

# A MkDocs/Zensical nav is a list of entries, each either `{title: url}` for a
# page or `{title: [children]}` for a section (a bare `url` string attaches
# a section index page, courtesy of the `navigation.indexes` feature).
NavItem = "str | dict[str, str | list[NavItem]]"

ROOT = Path(__file__).parent.parent.parent
API_DIR = ROOT / "docs" / "api"

# `src/mcp-types` is a distribution directory, not an import package, so each
# package's dotted module path is taken relative to its own parent: deriving
# it from `src/` would emit the unimportable `mcp-types.mcp_types.*`.
PACKAGES = (ROOT / "src" / "mcp", ROOT / "src" / "mcp-types" / "mcp_types")

_KIND_SECTIONS = {
    griffe.Kind.MODULE: "Modules",
    griffe.Kind.CLASS: "Classes",
    griffe.Kind.FUNCTION: "Functions",
    griffe.Kind.ATTRIBUTE: "Attributes",
    griffe.Kind.TYPE_ALIAS: "Type aliases",
}


class _Node:
    """A module (`url`) and/or a package with child modules (`children`)."""

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


def _compact_index(module: griffe.Module, documented: set[str]) -> str | None:
    """Build a compact page body for a module that re-exports from outside its own subtree.

    mkdocstrings renders a re-export whose canonical documentation lives on
    another page as a full duplicate of it, whether the alias stays within
    one top-level package (`mcp.client.auth` re-exporting from
    `mcp.shared.auth`) or crosses packages (`from mcp_types import y` +
    `__all__` — `load_external_modules` in mkdocs.yml has the collector chase
    exported cross-package aliases when their package is first collected, so
    the target package is loaded regardless of page order). Modules whose
    exports all live in their own subtree (`mcp_types` re-exporting its
    private `._types` module, or a module whose `__all__` lists only its own
    definitions) are unaffected and keep the plain `::: module` stub (return
    `None`): their page is itself the canonical rendering.

    For an affected module, replace the duplicates: every export whose
    canonical page exists elsewhere under the API reference becomes a link to
    it, and only exports documented nowhere else (re-exports from private
    modules) keep their full body here, via an explicit `members:` list.
    """
    prefix = f"{module.path}."
    exports: dict[str, griffe.Object | griffe.Alias] = {}
    for export in module.exports or ():
        name = str(export)
        # Listed exports must be statically documentable: a name provided at
        # runtime (module `__getattr__`) is a docs error by policy, not a skip.
        if (member := module.members.get(name)) is None:
            msg = f"gen_ref_pages: export {module.path}.{name} is not statically visible"
            raise SystemExit(msg)
        exports[name] = member
    if not any(member.is_alias and not member.target_path.startswith(prefix) for member in exports.values()):
        return None

    # A plain stub also renders the module's own public members that are not
    # in `__all__` (`show_if_no_docstring: false` hides the docstring-less
    # ones); keep them, so flipping a page to compact drops nothing.
    public = dict(exports)
    for name, member in module.members.items():
        if (
            name not in public
            and not name.startswith("_")
            and not member.is_alias
            and member.kind is not griffe.Kind.MODULE
            and member.has_docstrings
        ):
            public[name] = member

    inline: list[str] = []
    sections: dict[str, list[str]] = {}
    for name in sorted(public, key=str.lower):
        member = public[name]
        try:
            target = member.final_target if member.is_alias else member
        except griffe.AliasResolutionError as exc:
            msg = f"gen_ref_pages: export {module.path}.{name} resolves outside the documented packages"
            raise SystemExit(msg) from exc
        # Link to the anchor another page actually renders: the deepest alias
        # hop whose module is documented (the final target may live in a
        # private module and only be re-exported by a public one), rendered
        # there only when docstringed (`show_if_no_docstring: false`).
        anchor = None
        hop = member
        while hop.is_alias:
            if hop.target_path.rpartition(".")[0] in documented:
                anchor = hop.target_path
            hop = hop.target
        if anchor is not None and member.has_docstrings:
            link_target = anchor
        else:
            inline.append(name)
            link_target = f"{module.path}.{name}"
        entry = f"- [`{name}`][{link_target}]"
        if docstring := target.docstring:
            summary = " ".join(docstring.value.split("\n\n", 1)[0].split("\n"))
            entry += f" — {summary}"
        sections.setdefault(_KIND_SECTIONS[target.kind], []).append(entry)

    body = [f"::: {module.path}", "    options:"]
    if inline:
        body += ["      members:", *(f"        - {name}" for name in inline)]
    else:
        body += ["      members: false"]
    body.append("")
    for title in _KIND_SECTIONS.values():
        if title in sections:
            body += [f"## {title}", "", *sections[title], ""]
    return "\n".join(body)


def _stub(title: str, body: str) -> str:
    """A stub page: explicit title frontmatter plus the page body.

    The explicit title matters: the stubs have no H1 of their own, and a
    title-less page falls back to "Index"/the filename — which is what
    pruned nav rows, browser tabs, and search results show.
    """
    return f'---\ntitle: "{title}"\n---\n\n{body.rstrip()}\n'


def generate() -> list[NavItem]:
    """Write `docs/api/**.md` stubs and return the API-section navigation."""
    if API_DIR.exists():
        shutil.rmtree(API_DIR)

    root = _Node()
    stubs: dict[Path, str] = {}
    pages: dict[str, Path] = {}
    documented: set[str] = set()

    for package in PACKAGES:
        base = package.parent
        for path in sorted(package.rglob("*.py")):
            module_path = path.relative_to(base).with_suffix("")
            doc_path = path.relative_to(base).with_suffix(".md")

            parts = tuple(module_path.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
                doc_path = doc_path.with_name("index.md")
            # A private component anywhere makes the module private: checking
            # only the leaf would publish pages for e.g. mcp._vendor.util.
            if any(part.startswith("_") for part in parts):
                continue

            ident = ".".join(parts)
            documented.add(ident)
            stubs[API_DIR / doc_path] = _stub(parts[-1], f"::: {ident}")
            pages[ident] = API_DIR / doc_path

            node = root
            for part in parts:
                node = node.child(part)
            node.url = f"api/{doc_path.as_posix()}"

    # Load the root packages before inspecting any module: aliases only
    # resolve once the module they point at is in the loader's collection.
    loader = griffe.GriffeLoader(search_paths=[str(package.parent) for package in PACKAGES])
    for package in PACKAGES:
        loader.load(package.name)
    for ident, doc_path in pages.items():
        try:
            module = loader.modules_collection[ident]
        except KeyError as exc:
            raise SystemExit(f"gen_ref_pages: cannot find {ident} in the loaded packages") from exc
        if not isinstance(module, griffe.Module):
            raise SystemExit(f"gen_ref_pages: {ident} is shadowed by a non-module member")
        if body := _compact_index(module, documented):
            stubs[doc_path] = _stub(ident.rpartition(".")[2], body)

    for full_doc_path, stub in stubs.items():
        full_doc_path.parent.mkdir(parents=True, exist_ok=True)
        full_doc_path.write_text(stub, encoding="utf-8")

    return [root.children[name].to_nav(name) for name in sorted(root.children)]


if __name__ == "__main__":
    generate()
