"""Produce the concrete Zensical build config from `mkdocs.yml`.

Zensical builds from `mkdocs.yml` directly, but it has no equivalent of
mkdocs-literate-nav: the "API Reference" navigation has to be materialised
as explicit entries. This script regenerates the `docs/api/` tree (via
gen_ref_pages) and writes `mkdocs.gen.yml` with the real API nav spliced
in — that generated file is what `zensical build`/`serve` consumes.

With `--lang CODE` it writes `mkdocs.CODE.gen.yml` for one translated site
instead: built from the tree `scripts/docs/translations.py stage` assembled
under `.build/i18n/CODE/docs/` into `site/CODE/`, with no API reference of its
own (its nav entry links the English one) and nav titles taken from the staged
pages (the headings `stage` recorded beside the tree). Every config, English
included, carries the language switcher (`extra.alternate`) built from
`i18n/languages.yml`, which this module also loads for the translation tool.

Usage:
    python scripts/docs/build_config.py [--lang CODE]
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Both scripts live in this directory, which Python puts on sys.path[0] when
# `build_config.py` is run directly (its documented invocation).
import gen_ref_pages
import yaml
from gen_ref_pages import NavItem

ROOT = Path(__file__).parent.parent.parent
LANGUAGES_FILE = "i18n/languages.yml"

# A language site carries no API reference; its nav entry links the English
# one (a sibling site one level up), which opens on the first package's index.
API_REFERENCE_URL = "../api/mcp/"

# A nav value with a URL scheme (https:, mailto:, ...), a leading `/`, or a
# leading `../` (out of this site) is a link, not a page under docs_dir.
_LINK = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:|/|\.\./")


@dataclass(frozen=True)
class Language:
    """One translated site from `i18n/languages.yml`."""

    code: str
    name: str
    theme: str
    hreflang: str


@dataclass(frozen=True)
class Registry:
    """The parsed `i18n/languages.yml`."""

    model: str
    exclude: list[str]
    languages: list[Language]


def load_registry(root: Path = ROOT) -> Registry:
    """Parse `i18n/languages.yml` under repository `root`.

    Raises:
        ValueError: The file is missing, unparsable, or not the shape of `Registry`.
    """
    try:
        raw = yaml.safe_load((root / LANGUAGES_FILE).read_text(encoding="utf-8"))
        languages = [Language(**entry) for entry in raw["languages"]]
        return Registry(str(raw["model"]), [str(pattern) for pattern in raw["exclude"]], languages)
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        raise ValueError(f"{LANGUAGES_FILE}: {exc!r}") from exc


def staged_docs_dir(code: str, root: Path = ROOT) -> Path:
    """Where `translations.py stage` assembles a language's docs tree before its site is built."""
    return root / ".build" / "i18n" / code / "docs"


def staged_titles_file(code: str, root: Path = ROOT) -> Path:
    """Where `translations.py stage` records each staged page's `#` heading text, keyed by page path."""
    return root / ".build" / "i18n" / code / "titles.json"


def nav_page_paths(nav: list[NavItem]) -> list[str]:
    """Every local page path in the nav, depth first in nav order (link entries excluded)."""
    paths: list[str] = []
    for entry in nav:
        value = next(iter(entry.values())) if isinstance(entry, dict) else entry
        if isinstance(value, list):
            paths.extend(nav_page_paths(value))
        elif not _LINK.match(value):
            paths.append(value)
    return paths


def language_nav(nav: list[NavItem], titles: dict[str, str]) -> list[NavItem]:
    """The nav of a language site: every title taken from the staged pages (`titles` maps page path to H1).

    Page labels are dropped, so Zensical titles each page from its (translated)
    H1, and a section is titled with the H1 of the index page that leads it, so
    the sidebar cannot drift from the pages. A link entry, and a section that
    does not lead with a titled page, keeps its English label.
    """
    entries: list[NavItem] = []
    for entry in nav:
        if isinstance(entry, str):
            entries.append(entry)
            continue
        ((label, value),) = entry.items()
        if isinstance(value, list):
            title = titles.get(value[0]) if value and isinstance(value[0], str) else None
            entries.append({title or label: language_nav(value, titles)})
        else:
            entries.append({label: value} if _LINK.match(value) else value)
    return entries


def alternate(languages: list[Language], lang: str | None = None) -> list[dict[str, str]]:
    """The `extra.alternate` switcher of the English site, or with `lang` of that language site.

    Each label leads with the site's code (`ja - 日本語`). Links are relative
    to the site being built (English one level up from a language site), so
    the theme's `url` filter makes them page-relative and a mirror keeps working.
    """
    up = "" if lang is None else "../"
    entries = [{"name": "en - English", "link": up or "./", "lang": "en"}]
    entries += [{"name": f"{o.code} - {o.name}", "link": f"{up}{o.code}/", "lang": o.hreflang} for o in languages]
    return entries


def _api_entry(nav: list[NavItem]) -> dict[str, str | list[NavItem]]:
    """The `mkdocs.yml` placeholder entry the API reference is spliced into."""
    for entry in nav:
        if isinstance(entry, dict) and "API Reference" in entry:
            return entry
    raise SystemExit("build_config: no 'API Reference' entry found in mkdocs.yml nav")


def _validate_nav(nav: list[NavItem], docs_dir: Path) -> None:
    """Fail on nav/page drift in either direction.

    Zensical (0.0.48) ships a nav entry for a nonexistent page as a broken
    link without any diagnostic even under --strict, and publishes a page
    that no nav entry reaches as unreachable orphan HTML; MkDocs aborted the
    build on both (--strict with `validation.omitted_files: warn`).
    Validating here keeps those guarantees. The generated `api/` tree is
    exempt from the orphan check: its nav is spliced in from the same
    generator that writes the files, so it cannot drift.
    """
    pages = set(nav_page_paths(nav))
    # Containment before existence: `docs_dir / page` would happily resolve
    # a `../` escape against the wrong root.
    if escaping := sorted(page for page in pages if posixpath.normpath(page).startswith("..")):
        raise SystemExit(f"build_config: nav references pages outside {docs_dir}: {escaping}")
    if missing := sorted(page for page in pages if not (docs_dir / page).is_file()):
        raise SystemExit(f"build_config: nav references pages that don't exist under {docs_dir}: {missing}")
    # Dot-directories (e.g. `.overrides` theme files) are not pages: the site
    # builder ignores them, so the orphan check must too.
    relative = (page.relative_to(docs_dir) for page in docs_dir.rglob("*.md"))
    on_disk = {page.as_posix() for page in relative if not any(part.startswith(".") for part in page.parts)}
    if orphaned := sorted(page for page in on_disk - pages if not page.startswith("api/")):
        raise SystemExit(f"build_config: pages under {docs_dir} that no nav entry reaches: {orphaned}")


def build_config(lang: str | None = None, root: Path = ROOT) -> Path:
    """Write the English config, or with `lang` that language site's config; returns the file written.

    `root` is the repository the config is read from and written to (a
    scratch tree in tests); the English API reference is always generated
    from this checkout's `src/`.
    """
    config: dict[str, Any] = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))
    try:
        # No registry yet means English is the only site there is.
        no_languages = lang is None and not (root / LANGUAGES_FILE).is_file()
        languages = [] if no_languages else load_registry(root).languages
    except ValueError as exc:
        raise SystemExit(f"build_config: {exc}") from exc
    if languages:  # a switcher listing English alone is noise
        config.setdefault("extra", {})["alternate"] = alternate(languages, lang)

    if lang is None:
        api_nav: list[NavItem] = gen_ref_pages.generate()
        if not api_nav:
            raise SystemExit("build_config: gen_ref_pages produced no API pages — did the src/ layout move?")
        _api_entry(config["nav"])["API Reference"] = api_nav
        docs_dir = root / "docs"
        output = root / "mkdocs.gen.yml"
    else:
        language = next((candidate for candidate in languages if candidate.code == lang), None)
        if language is None:
            raise SystemExit(f"build_config: unknown language {lang!r} (see {LANGUAGES_FILE})")
        docs_dir, titles_file = staged_docs_dir(lang, root), staged_titles_file(lang, root)
        try:  # written last by `stage`, so its presence means the tree beside it is complete
            titles: dict[str, str] = json.loads(titles_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(
                f"build_config: cannot read {titles_file} (run translations.py stage --lang {lang})"
            ) from exc
        _api_entry(config["nav"])["API Reference"] = API_REFERENCE_URL
        config["nav"] = language_nav(config["nav"], titles)
        # No API reference on a language site, so no mkdocstrings pass either.
        plugins: list[str | dict[str, Any]] = config["plugins"]
        config["plugins"] = [p for p in plugins if (next(iter(p)) if isinstance(p, dict) else p) != "mkdocstrings"]
        # A stored translation can name a `docs_src` file an English change has since renamed:
        # that block renders empty under the outdated notice instead of stopping the build.
        extensions: list[str | dict[str, Any]] = config["markdown_extensions"]
        for extension in extensions:
            if isinstance(extension, dict) and extension.get("pymdownx.snippets"):
                extension["pymdownx.snippets"]["check_paths"] = False
        config["theme"]["language"] = language.theme
        # Zensical resolves docs_dir/site_dir against the config file and
        # rejects absolute paths.
        config["docs_dir"] = docs_dir.relative_to(root).as_posix()
        config["site_dir"] = f"site/{lang}"
        config["site_url"] = config["site_url"].rstrip("/") + f"/{lang}/"
        output = root / f"mkdocs.{lang}.gen.yml"

    _validate_nav(config["nav"], docs_dir)
    output.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", metavar="CODE", help="write the config of this language site instead of English")
    build_config(parser.parse_args().lang)


if __name__ == "__main__":
    main()
