"""Produce the concrete Zensical build config from `mkdocs.yml`.

Zensical builds from `mkdocs.yml` directly, but it has no equivalent of
mkdocs-literate-nav: the "API Reference" navigation has to be materialised
as explicit entries. This script regenerates the API reference tree (via
gen_ref_pages) and writes `mkdocs.gen.yml` with the real API nav spliced
in — that generated file is what `zensical build`/`serve` consumes.

With `--lang <code>` it writes `mkdocs.<code>.gen.yml` for one translated
site instead: `docs_dir` pointed at that language's staged tree (see
`scripts/docs/i18n`), the theme language switched, the sidebar labels swapped
for the language's generated renderings (a label without one stays English),
and the site published under `/<code>/`. A language site does not rebuild
the API reference — its "API Reference" nav entry links to the single English
one — so it runs no mkdocstrings pass.

Every config, English included, carries the same `extra.alternate` list (the
language switcher and each page's `hreflang` alternates), and that list is the
set of sites the build actually produces: `--switcher-languages` names them
(the build script passes the same value to every config it writes), so a
partial or English-only build never links to a site it did not make. With
the flag omitted the list is every enabled language.

`--site-url` names the URL the site is served from — production
(`mkdocs.yml`'s `site_url`) unless the build script says otherwise (a PR
preview at its own host) — and everything absolute this build bakes derives
from it: each config's `site_url`, the switcher links' path prefix, and the
API-reference entry a language site's nav points at.

Usage:
    python scripts/docs/build_config.py [--site-url URL] [--switcher-languages ja,ko]
    python scripts/docs/build_config.py --lang <code> [--docs-dir DIR] [--site-url URL] [--switcher-languages ...]
"""

from __future__ import annotations

import argparse
import posixpath
from pathlib import Path
from urllib.parse import urlsplit

# Both scripts live in this directory, which Python puts on sys.path[0] when
# `build_config.py` is run directly (its documented invocation).
import gen_ref_pages
import yaml
from llms_txt import page_url
from navigation import NavEntry, nav_pages, relabel_nav

from i18n.config import ConfigError, Registry, load_registry, nav_path, staged_docs_dir, staged_site_dir
from i18n.nav import load_nav

ROOT = Path(__file__).parent.parent.parent


def _validate_nav(nav: list[NavEntry], docs_dir: Path) -> None:
    """Fail on nav/page drift in either direction.

    Zensical (0.0.48) ships a nav entry for a nonexistent page as a broken
    link without any diagnostic even under --strict, and publishes a page
    that no nav entry reaches as unreachable orphan HTML; MkDocs aborted the
    build on both (--strict with `validation.omitted_files: warn`).
    Validating here keeps those guarantees. The generated `api/` tree is
    exempt from the orphan check: its nav is spliced in from the same
    generator that writes the files, so it cannot drift.
    """
    pages = set(nav_pages(nav))
    # Containment before existence: `docs_dir / page` would happily resolve
    # an absolute value or a `../` escape against the wrong root.
    if escaping := sorted(p for p in pages if p.startswith("/") or posixpath.normpath(p).startswith("..")):
        raise SystemExit(f"build_config: nav references pages outside docs/: {escaping}")
    if missing := sorted(page for page in pages if not (docs_dir / page).is_file()):
        raise SystemExit(f"build_config: nav references pages that don't exist under {docs_dir}: {missing}")
    # Dot-directories (e.g. `.overrides` theme files) are not pages: the site
    # builder ignores them, so the orphan check must too.
    relative = (page.relative_to(docs_dir) for page in docs_dir.rglob("*.md"))
    on_disk = {page.as_posix() for page in relative if not any(part.startswith(".") for part in page.parts)}
    if orphaned := sorted(page for page in on_disk - pages if not page.startswith("api/")):
        raise SystemExit(f"build_config: pages under {docs_dir} that no nav entry reaches: {orphaned}")


def _api_nav_entry(nav: list[NavEntry]) -> dict[str, str | list[NavEntry]]:
    """The `mkdocs.yml` placeholder nav entry the API reference is spliced into."""
    for entry in nav:
        if isinstance(entry, dict) and "API Reference" in entry:
            return entry
    raise SystemExit("build_config: no 'API Reference' entry found in mkdocs.yml nav")


def _alternate(registry: Registry, codes: list[str] | None, base: str) -> list[dict[str, str]]:
    """The language-switcher entries: English at the site root, then each built language site.

    `codes` are the language sites this build produces (None means every
    enabled language); the switcher must never offer a site that isn't built.
    Each `link` is the site root's path plus the language code (`base` is
    the site URL), so the switcher follows whatever host and path the site
    is served under.

    Raises:
        SystemExit: A named language is not an enabled entry of the registry.
    """
    if codes is None:
        languages = registry.enabled
    else:
        try:
            languages = [registry.language(code) for code in codes]
        except ConfigError as exc:
            raise SystemExit(f"build_config: --switcher-languages: {exc}") from exc
        if disabled := [language.code for language in languages if not language.enabled]:
            raise SystemExit(f"build_config: --switcher-languages names disabled languages: {disabled}")
    root = urlsplit(base).path.rstrip("/") + "/"
    entries = [{"name": "English", "link": root, "lang": "en"}]
    entries += [
        {"name": language.name, "link": f"{root}{language.code}/", "lang": language.hreflang} for language in languages
    ]
    return entries


def _repo_relative(path: Path, what: str) -> str:
    """`path` as a repo-root-relative posix path (Zensical resolves config paths against the config file).

    Both sides are resolved before the comparison, so a repository reached
    through a symlinked path still yields the same relative form.

    Raises:
        SystemExit: `path` does not live inside the repository.
    """
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise SystemExit(f"build_config: {what} {path} must live inside the repository") from exc


def _translated_labels(lang: str) -> dict[str, str]:
    """The language's translated nav labels; empty when it has no nav map yet."""
    try:
        nav = load_nav(nav_path(lang))
    except ConfigError as exc:
        raise SystemExit(f"build_config: {exc}") from exc
    return {} if nav is None else nav.labels


def build_config(
    lang: str | None = None,
    docs_dir: Path | None = None,
    site_url: str | None = None,
    switcher_languages: list[str] | None = None,
) -> Path:
    """Write the concrete build config; returns its path.

    `switcher_languages` are the language sites this build produces (None
    means every enabled language); a language config must be one of them.
    """
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    registry = load_registry()
    if lang is not None and switcher_languages is not None and lang not in switcher_languages:
        raise SystemExit(f"build_config: --switcher-languages must include the site being built ({lang})")
    base = (site_url or config["site_url"]).rstrip("/")

    if lang is None:
        if docs_dir is not None:
            raise SystemExit("build_config: --docs-dir applies only to a language build (pass --lang)")
        docs = ROOT / "docs"
        api_nav = gen_ref_pages.generate()
        if not api_nav:
            raise SystemExit("build_config: gen_ref_pages produced no API pages — did the src/ layout move?")
        _api_nav_entry(config["nav"])["API Reference"] = api_nav
    else:
        docs = docs_dir if docs_dir is not None else staged_docs_dir(lang, ROOT)
        # A language site links the one English API reference instead of
        # rebuilding it: no mkdocstrings pass, and the nav entry is an
        # external link to the reference on the English site (staging points
        # prose links into `api/` at the same place).
        config["plugins"] = [p for p in config["plugins"] if not (isinstance(p, dict) and "mkdocstrings" in p)]
        _api_nav_entry(config["nav"])["API Reference"] = f"{base}/{page_url(gen_ref_pages.ENTRY_PAGE)}"
    if not docs.is_dir():
        raise SystemExit(f"build_config: docs directory {docs} does not exist (stage the language first)")

    _validate_nav(config["nav"], docs)

    config.setdefault("extra", {})["alternate"] = _alternate(registry, switcher_languages, base)
    if lang is None:
        config["site_url"] = f"{base}/"
        output = ROOT / "mkdocs.gen.yml"
    else:
        language = registry.language(lang)
        # The sidebar reads in the site's language: every label the language's
        # generated nav map covers ("API Reference" included) is swapped for
        # its rendering; the rest stay English. Never applied to the English config.
        config["nav"] = relabel_nav(config["nav"], _translated_labels(lang))
        # Zensical resolves these against the config file's directory and
        # requires them relative to it; an absolute path aborts the build.
        config["docs_dir"] = _repo_relative(docs, "docs directory")
        config["site_dir"] = _repo_relative(staged_site_dir(lang, ROOT), "site directory")
        config["site_url"] = f"{base}/{lang}/"
        config["theme"]["language"] = language.theme_language
        output = ROOT / f"mkdocs.{lang}.gen.yml"

    output.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return output


def _language_codes(value: str) -> list[str]:
    """The comma-separated language codes of `--switcher-languages` (empty means English only)."""
    return [code.strip() for code in value.split(",") if code.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", metavar="CODE", help="Build config for this language site.")
    parser.add_argument(
        "--docs-dir", type=Path, help="Docs tree for a --lang build (default: the language's staged tree)."
    )
    parser.add_argument(
        "--site-url",
        help="URL the site is served from; every absolute link the build bakes derives from it"
        " (default: mkdocs.yml site_url).",
    )
    parser.add_argument(
        "--switcher-languages",
        type=_language_codes,
        metavar="CODES",
        help="Comma-separated codes of the language sites this build produces, listed by the "
        "language switcher (empty: English only; default: every enabled language).",
    )
    args = parser.parse_args()
    print(build_config(args.lang, args.docs_dir, args.site_url, args.switcher_languages))


if __name__ == "__main__":
    main()
