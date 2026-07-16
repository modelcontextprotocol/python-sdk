"""Fail the docs build when API rendering depends on page processing order.

Zensical discovers pages with an unsorted directory walk and renders them
all through one shared mkdocstrings handler, so the griffe collection that
resolves `::: module` blocks accumulates in filesystem-dependent order, and
nothing in the toolchain checks that the order is safe: a cross-package
re-export that only resolved when its target package had been collected
earlier built fine on one machine and died with `AliasResolutionError` on
another (a GitHub runner-image update reshuffled readdir order and broke
every CI docs build this way). `load_external_modules: true` in `mkdocs.yml`
makes resolution order-independent; this check enforces that property,
because a regular build only ever exercises one arbitrary order.

mkdocstrings applies module loading and per-page options only on the first
collect of a package (later pages find the package already collected), so
each package under `docs/api/` gets the two hostile sides of that
asymmetry, each from a fresh handler with an empty collection:

- its subpages first and its package index last, so pages rendering
  cross-package re-exports (the index above all) come after a plain
  subpage has already collected the package and nothing they declare
  themselves can still affect collection;
- its package index alone, so the page with the most re-exports is itself
  the first collect over an empty collection.

Only the package's own pages are rendered: resolving `mcp` re-exports
without ever rendering an `mcp_types` page is exactly the property under
test.

Usage:
    python scripts/docs/check_render_order.py [--config mkdocs.gen.yml]

Run after `build_config.py` has produced the config and the `docs/api/`
tree.
"""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

# Sibling modules, same direct-invocation pattern as build_config.py:
# gen_ref_pages owns the docs/api layout, llms_txt owns the page-URL mapping.
import gen_ref_pages
from llms_txt import page_url
from zensical.compat import mkdocstrings as zensical_mkdocstrings
from zensical.config import parse_config
from zensical.markdown.render import render

API_DIR = gen_ref_pages.API_DIR
DOCS_DIR = API_DIR.parent


def _passes(package: str, pages: list[Path]) -> list[tuple[str, list[Path]]]:
    """The labeled render orders exercising both sides of the first-collect asymmetry."""
    index = API_DIR / package / "index.md"
    if index not in pages:
        return [(f"'{package}'", pages)]
    subpages = [page for page in pages if page != index]
    if not subpages:
        return [(f"'{package}' index-alone", [index])]
    return [(f"'{package}' index-last", [*subpages, index]), (f"'{package}' index-alone", [index])]


def _render(page: Path) -> None:
    """Render one page the way Zensical's Rust core drives the Python side."""
    rel = page.relative_to(DOCS_DIR).as_posix()
    render(page.read_text(encoding="utf-8"), rel, page_url(rel))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default=str(gen_ref_pages.ROOT / "mkdocs.gen.yml"), help="Built config to render with"
    )
    args = parser.parse_args()
    parse_config(args.config)

    packages: dict[str, list[Path]] = {}
    for page in sorted(API_DIR.rglob("*.md")):
        packages.setdefault(page.relative_to(API_DIR).parts[0], []).append(page)
    if not packages:
        raise SystemExit(f"check_render_order: no pages under {API_DIR} (run build_config.py first)")

    for package in sorted(packages):
        for label, order in _passes(package, packages[package]):
            # Fresh Handlers -> empty griffe collection. Autorefs anchors
            # accumulate across passes, but they play no part in collection
            # or alias resolution (check_crossrefs owns link health).
            zensical_mkdocstrings.reset()
            for position, page in enumerate(order):
                try:
                    _render(page)
                # Top-level handler: any exception from any page fails the
                # check; the traceback identifies whether the order was at
                # fault or something else broke (network, missing file).
                except Exception:
                    traceback.print_exc()
                    rel = page.relative_to(DOCS_DIR).as_posix()
                    raise SystemExit(
                        f"check_render_order: {rel} failed at position {position + 1}/{len(order)} of the"
                        f" {label} order (traceback above; an AliasResolutionError means API rendering"
                        " depends on page order — see `load_external_modules` in mkdocs.yml)"
                    ) from None
            print(f"check_render_order: {label} order OK ({len(order)} pages)")


if __name__ == "__main__":
    main()
