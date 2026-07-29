"""Produce the concrete Zensical build config from `mkdocs.yml`.

Zensical builds from `mkdocs.yml` directly, but it has no equivalent of
mkdocs-literate-nav: the "API Reference" navigation has to be materialised
as explicit entries. This script regenerates the `docs/api/` tree (via
gen_ref_pages) and writes `mkdocs.gen.yml` with the real API nav spliced
in — that generated file is what `zensical build`/`serve` consumes.

Usage:
    python scripts/docs/build_config.py
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

# Both scripts live in this directory, which Python puts on sys.path[0] when
# `build_config.py` is run directly (its documented invocation).
import gen_ref_pages
import yaml

ROOT = Path(__file__).parent.parent.parent

# A scheme-prefixed nav value (https:, mailto:, ...) is an external link, not
# a page path (same classifier as llms_txt.py; a `://` test would misread
# scheme-only URIs as pages).
_EXTERNAL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")


def _nav_pages(nav: list) -> set[str]:
    """Collect every local page reference in the nav (external links excluded)."""
    pages: set[str] = set()
    for entry in nav:
        value = next(iter(entry.values())) if isinstance(entry, dict) else entry
        if isinstance(value, list):
            pages |= _nav_pages(value)
        elif not _EXTERNAL.match(value):
            pages.add(value)
    return pages


def _validate_nav(nav: list, docs_dir: Path) -> None:
    """Fail on nav/page drift in either direction.

    Zensical (0.0.48) ships a nav entry for a nonexistent page as a broken
    link without any diagnostic even under --strict, and publishes a page
    that no nav entry reaches as unreachable orphan HTML; MkDocs aborted the
    build on both (--strict with `validation.omitted_files: warn`).
    Validating here keeps those guarantees. The generated `api/` tree is
    exempt from the orphan check: its nav is spliced in from the same
    generator that writes the files, so it cannot drift.
    """
    pages = _nav_pages(nav)
    # Containment before existence: `docs_dir / page` would happily resolve
    # an absolute value or a `../` escape against the wrong root.
    if escaping := sorted(p for p in pages if p.startswith("/") or posixpath.normpath(p).startswith("..")):
        raise SystemExit(f"build_config: nav references pages outside docs/: {escaping}")
    if missing := sorted(page for page in pages if not (docs_dir / page).is_file()):
        raise SystemExit(f"build_config: nav references pages that don't exist under docs/: {missing}")
    # Dot-directories (e.g. `.overrides` theme files) are not pages: the site
    # builder ignores them, so the orphan check must too.
    relative = (page.relative_to(docs_dir) for page in docs_dir.rglob("*.md"))
    on_disk = {page.as_posix() for page in relative if not any(part.startswith(".") for part in page.parts)}
    if orphaned := sorted(page for page in on_disk - pages if not page.startswith("api/")):
        raise SystemExit(f"build_config: pages under docs/ that no nav entry reaches: {orphaned}")


def build_config() -> None:
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))

    api_nav = gen_ref_pages.generate()
    if not api_nav:
        raise SystemExit("build_config: gen_ref_pages produced no API pages — did the src/ layout move?")
    for entry in config["nav"]:
        if isinstance(entry, dict) and "API Reference" in entry:
            entry["API Reference"] = api_nav
            break
    else:
        raise SystemExit("build_config: no 'API Reference' entry found in mkdocs.yml nav")

    _validate_nav(config["nav"], ROOT / "docs")

    output = ROOT / "mkdocs.gen.yml"
    output.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    build_config()
