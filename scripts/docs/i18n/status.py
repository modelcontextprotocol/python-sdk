"""Compute a language's page-by-page (and nav) translation status from the working tree.

This is the read-only join of the three sources of truth — the nav (what
should exist, and the sidebar labels), the English pages plus the language's
prompt inputs (what a translation would be fingerprinted with today), and the
language's generated files (what its translations were fingerprinted with) —
that `status`, `translate` selection and the build's banners all consume. An
outdated page whose links the English page has since moved on from is named
as such: staging shows the English page in its place until it is refreshed,
and its reason says why.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# scripts/docs is the import root: the nav walker is shared with the build's
# config generator, which imports it the same way.
from navigation import nav_labels

from i18n.config import DOCS, I18N_DIR, ConfigError, Language, nav_path, pages_dir, state_path
from i18n.inputs import LanguageInputs, load_inputs
from i18n.nav import NavStatus, NavTranslation, classify_nav, load_nav
from i18n.pages import translatable_pages
from i18n.stage import STALE_LINKS_REASON, staged_paths, stale_document_links
from i18n.state import Fingerprint, LanguageState, PageStatus, classify, load_state


@dataclass(frozen=True)
class LanguageStatus:
    """A language's inputs, state, and the classification of every page and of its nav map."""

    inputs: LanguageInputs
    state: LanguageState
    pages: list[PageStatus]
    labels: list[str]
    nav: NavTranslation | None
    nav_status: NavStatus

    def select(self, *statuses: str) -> list[str]:
        """The pages currently in any of the given states, in nav order."""
        return [page.page for page in self.pages if page.status in statuses]


def language_status(
    language: Language,
    nav: list[Any],
    exclude_pages: tuple[str, ...],
    *,
    site_name: str,
    docs: Path = DOCS,
    i18n_dir: Path = I18N_DIR,
) -> LanguageStatus:
    """Classify one language's pages and nav map against the current English tree.

    Raises:
        ConfigError: A prompt input, generated file, or English page cannot be read.
    """
    inputs = load_inputs(language, i18n_dir)
    state = load_state(state_path(language.code, i18n_dir))
    translations = pages_dir(language.code, i18n_dir)
    current: dict[str, Fingerprint] = {}
    for page in translatable_pages(nav, exclude_pages):
        try:
            english = (docs / page).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"nav lists {page}, which is missing from {docs}: {exc}") from exc
        current[page] = inputs.fingerprint(english)
    translated = {page for page in current if (translations / page).is_file()}
    labels = nav_labels(nav, site_name=site_name)
    nav_map = load_nav(nav_path(language.code, i18n_dir))
    present = staged_paths(docs)
    pages = [
        _with_stale_links_reason(status, docs, translations, present) for status in classify(current, state, translated)
    ]
    return LanguageStatus(
        inputs=inputs,
        state=state,
        pages=pages,
        labels=labels,
        nav=nav_map,
        nav_status=classify_nav(labels, inputs.nav_fingerprint(labels), nav_map),
    )


def _with_stale_links_reason(status: PageStatus, docs: Path, translations: Path, present: set[str]) -> PageStatus:
    """`status`, plus the reason an outdated page will read in English until refreshed.

    An outdated translation still linking a page the English tree has since
    renamed or dropped cannot go on the site as it stands; staging shows the
    English page in its place, and `status` says so, so the maintainer knows
    why. (A current page's links match its unchanged English source, so it
    can only differ from the English by a hand-edit — an integrity failure
    that `check` reports rather than staleness.)
    """
    if status.status != "outdated":
        return status
    english = (docs / status.page).read_text(encoding="utf-8")
    translated = (translations / status.page).read_text(encoding="utf-8")
    if not stale_document_links(translated, english, status.page, present):
        return status
    return replace(status, reasons=(*status.reasons, STALE_LINKS_REASON))
