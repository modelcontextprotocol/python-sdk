"""Produce the concrete Zensical build config from `mkdocs.yml`.

Zensical builds from `mkdocs.yml` directly, but it has no equivalent of
mkdocs-literate-nav: the "API Reference" navigation has to be materialised
as explicit entries. This script regenerates the `docs/api/` tree (via
gen_ref_pages) and writes `mkdocs.gen.yml` with the real API nav spliced
in — that generated file is what `zensical build`/`serve` consumes.

With `--lang <code>` it writes `mkdocs.<code>.gen.yml` for a translated
language site instead: built from the staged tree the translation tool made
(`.build/i18n/<code>/docs`, see scripts/docs/translations.py) into `site/<code>/`,
with the sidebar labels translated and no API reference of its own — its API
entry links the English reference. Every config carries the same language
switcher (`extra.alternate`) listing the English site and each language site
this build produces (`--languages`, default: all enabled).

Usage:
    python scripts/docs/build_config.py [--site-url URL] [--languages a,b] [--lang CODE]
"""

from __future__ import annotations

import argparse
import posixpath
import re
from pathlib import Path

# Both scripts live in this directory, which Python puts on sys.path[0] when
# `build_config.py` is run directly (its documented invocation).
import gen_ref_pages
import translations
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


def _relabel(nav: list, labels: dict[str, str]) -> list:
    """The nav with each translated sidebar label swapped in (page paths and unmapped labels untouched)."""
    out = []
    for entry in nav:
        if isinstance(entry, str):
            out.append(entry)
            continue
        ((label, value),) = entry.items()
        out.append({labels.get(label, label): _relabel(value, labels) if isinstance(value, list) else value})
    return out


def build_config(lang: str | None = None, site_url: str | None = None, codes: list[str] | None = None) -> Path:
    """Write the concrete config for the English site, or with `lang` for that language site.

    `site_url` is the URL the site is served from (mkdocs.yml's by default; a
    PR preview passes its own host) and `codes` the language sites this build
    produces, which is exactly what the language switcher offers.
    """
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    registry = translations.load_registry()
    base = (site_url or config["site_url"]).rstrip("/")
    switched = registry.languages if codes is None else [registry.language(code) for code in codes]
    if switched:  # the same switcher on every site, listing exactly the language sites this build produces
        config.setdefault("extra", {})["alternate"] = [
            {"name": "English", "link": f"{base}/", "lang": "en"},
            *({"name": la.name, "link": f"{base}/{la.code}/", "lang": la.hreflang} for la in switched),
        ]
    api = next((entry for entry in config["nav"] if isinstance(entry, dict) and "API Reference" in entry), None)
    if api is None:
        raise SystemExit("build_config: no 'API Reference' entry found in mkdocs.yml nav")

    if lang is None:
        api_nav = gen_ref_pages.generate()
        if not api_nav:
            raise SystemExit("build_config: gen_ref_pages produced no API pages — did the src/ layout move?")
        api["API Reference"] = api_nav
        docs = ROOT / "docs"
        config["site_url"] = f"{base}/"
        output = ROOT / "mkdocs.gen.yml"
    else:
        # A language site carries no API reference of its own: its nav entry
        # (and its prose links, rewritten at staging) point at the English one.
        api["API Reference"] = f"{base}/api/mcp/"
        config["plugins"] = [p for p in config["plugins"] if not (isinstance(p, dict) and "mkdocstrings" in p)]
        config["nav"] = _relabel(config["nav"], translations.load_state(lang)["ui"].get("strings", {}))
        config["theme"]["language"] = registry.language(lang).theme_language
        docs = translations.staged_docs(lang)
        config["docs_dir"] = f".build/i18n/{lang}/docs"
        config["site_dir"] = f"site/{lang}"
        config["site_url"] = f"{base}/{lang}/"
        output = ROOT / f"mkdocs.{lang}.gen.yml"

    _validate_nav(config["nav"], docs)
    output.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", metavar="CODE", help="build the config for this language site")
    parser.add_argument("--site-url", metavar="URL", help="URL the site is served from (default: mkdocs.yml)")
    parser.add_argument("--languages", metavar="a,b", help="language sites this build produces (default: all)")
    args = parser.parse_args()
    codes = None if args.languages is None else [c.strip() for c in args.languages.split(",") if c.strip()]
    print(f"wrote {build_config(args.lang, args.site_url, codes).relative_to(ROOT)}")
