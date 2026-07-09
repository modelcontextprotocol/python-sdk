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


def _compact_index(package: griffe.Module, documented: set[str]) -> str | None:
    """Build a compact index body for a package that re-exports another package's API.

    mkdocstrings renders a member re-exported across a package boundary
    (`from other_package import y` + `__all__`) as a full duplicate of its
    canonical documentation whenever the other package happens to be loaded
    already, and silently omits it when it isn't — which of the two a package
    index gets depends on page rendering order. Same-package re-exports
    (`mcp_types` re-exporting its private `._types` module) always resolve
    and are unaffected, so such packages keep the plain `::: package` stub
    (return `None`) and their index remains the full, canonical rendering.

    For an affected package, pin the semantics instead of inheriting the
    accident: every export whose canonical page exists elsewhere under the API
    reference becomes a link to it, and only exports documented nowhere else
    (re-exports from private modules) keep their full body here, via an
    explicit `members:` list.
    """
    prefix = f"{package.path}."
    exports = {str(export): package.members[str(export)] for export in package.exports or ()}
    if not any(member.is_alias and not member.target_path.startswith(prefix) for member in exports.values()):
        return None

    inline: list[str] = []
    sections: dict[str, list[str]] = {}
    for name in sorted(exports, key=str.lower):
        member = exports[name]
        # A target only gets an anchor on its canonical page if it is rendered
        # there, which the default `show_if_no_docstring: false` limits to
        # objects with docstrings.
        if member.is_alias and member.target_path.rpartition(".")[0] in documented and member.has_docstrings:
            link_target = member.target_path
        else:
            inline.append(name)
            link_target = f"{package.path}.{name}"
        entry = f"- [`{name}`][{link_target}]"
        try:
            target = member.final_target if member.is_alias else member
        except griffe.AliasResolutionError as exc:
            msg = f"gen_ref_pages: export {package.path}.{name} resolves outside the documented packages"
            raise SystemExit(msg) from exc
        if docstring := target.docstring:
            summary = " ".join(docstring.value.split("\n\n", 1)[0].split("\n"))
            entry += f" — {summary}"
        sections.setdefault(_KIND_SECTIONS[target.kind], []).append(entry)

    # Rendering the stub resolves the cross-package aliases again, in
    # mkdocstrings' own collection. On a warm incremental rebuild the target
    # package's pages can all be cache hits, so nothing else loads it and the
    # resolution crashes (AliasResolutionError); preloading pins it.
    preload = sorted(
        {member.target_path.split(".")[0] for member in exports.values() if member.is_alias} - {package.path}
    )
    body = [f"::: {package.path}", "    options:"]
    body += ["      preload_modules:", *(f"        - {module}" for module in preload)]
    if inline:
        body += ["      members:", *(f"        - {name}" for name in inline)]
    else:
        body += ["      members: false"]
    body.append("")
    for title in _KIND_SECTIONS.values():
        if title in sections:
            body += [f"## {title}", "", *sections[title], ""]
    return "\n".join(body)


def generate() -> list[NavItem]:
    """Write `docs/api/**.md` stubs and return the API-section navigation."""
    if API_DIR.exists():
        shutil.rmtree(API_DIR)

    root = _Node()
    stubs: dict[Path, str] = {}
    package_index: dict[str, Path] = {}
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
            stubs[API_DIR / doc_path] = f"::: {ident}\n"
            if len(parts) == 1:
                package_index[ident] = API_DIR / doc_path

            node = root
            for part in parts:
                node = node.child(part)
            node.url = f"api/{doc_path.as_posix()}"

    # Load every package before inspecting any of them: aliases only resolve
    # once the module they point at is in the loader's collection.
    loader = griffe.GriffeLoader(search_paths=[str(package.parent) for package in PACKAGES])
    modules = {ident: loader.load(ident) for ident in package_index}
    for ident, doc_path in package_index.items():
        module = modules[ident]
        assert isinstance(module, griffe.Module)
        if body := _compact_index(module, documented):
            stubs[doc_path] = body

    for full_doc_path, stub in stubs.items():
        full_doc_path.parent.mkdir(parents=True, exist_ok=True)
        full_doc_path.write_text(stub, encoding="utf-8")

    return [root.children[name].to_nav(name) for name in sorted(root.children)]


if __name__ == "__main__":
    generate()
