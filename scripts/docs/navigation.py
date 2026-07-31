"""The `mkdocs.yml` navigation shape, its walkers, and the external-link classifier.

Shared by the build (`build_config.py` validates the nav against the docs
tree and swaps in a language's translated labels, `gen_ref_pages.py` emits the
API entries, and `llms_txt.py` walks the nav into its page index and its
sections) and the translation tool (`i18n/`, whose translatable set is the
nav's prose pages, whose label map is the nav's human labels, and whose
staging classifies link targets), so all of them agree on the nav's shape, on
what counts as a local page path versus an external link, and on which strings
are the labels a reader sees. The one place a nav entry's shape is read is
`nav_item`; every walker here and elsewhere builds on it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TypeAlias

# A nav is a list of entries, each a bare page path or a single-key
# `{title: value}` mapping whose value is a page path, an external URL, or a
# nested list of entries (a bare path in a section attaches the section's
# index page, courtesy of the `navigation.indexes` feature).
NavEntry: TypeAlias = "str | dict[str, str | list[NavEntry]]"
NavValue: TypeAlias = "str | list[NavEntry]"

# A scheme-prefixed nav value or link target (https:, mailto:, ...) is an
# external link, not a page path (a `://` test would misread scheme-only URIs
# such as `mailto:` as pages).
EXTERNAL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass(frozen=True)
class NavPage:
    """A local page entry: its path as written, and its explicit label (None for a bare path)."""

    path: str
    label: str | None


def nav_item(entry: NavEntry) -> tuple[str | None, NavValue]:
    """One nav entry as `(label, value)`: the label is None for a bare page path.

    The value is a page path, an external URL, or a nested list of entries.
    """
    if isinstance(entry, dict):
        return next(iter(entry.items()))
    return None, entry


def nav_page_entries(nav: list[NavEntry]) -> list[NavPage]:
    """Every local page entry with its label, depth first in nav order (external links excluded)."""
    entries: list[NavPage] = []
    for entry in nav:
        label, value = nav_item(entry)
        if isinstance(value, list):
            entries.extend(nav_page_entries(value))
        elif not EXTERNAL.match(value):
            entries.append(NavPage(value, label))
    return entries


def nav_pages(nav: list[NavEntry]) -> list[str]:
    """Every local page reference in the nav, in nav order (external links excluded)."""
    return [entry.path for entry in nav_page_entries(nav)]


def nav_labels(nav: list[NavEntry], *, site_name: str) -> list[str]:
    """The nav's human-readable labels, in nav order and each listed once.

    A section title and an explicit `Label: value` entry both carry a label,
    external-link entries included; a bare page path carries none (its title
    comes from the page itself), and the site name is the product name rather
    than translatable text.
    """
    return list(dict.fromkeys(label for label in _labels(nav) if label != site_name))


def _labels(nav: list[NavEntry]) -> Iterator[str]:
    """Every explicit label in the nav, depth first, duplicates and all."""
    for entry in nav:
        label, value = nav_item(entry)
        if label is not None:
            yield label
        if isinstance(value, list):
            yield from _labels(value)


def relabel_nav(nav: list[NavEntry], labels: Mapping[str, str]) -> list[NavEntry]:
    """The nav with each label found in `labels` replaced by its mapped value, everything else as written."""
    relabelled: list[NavEntry] = []
    for entry in nav:
        label, value = nav_item(entry)
        if label is None:
            relabelled.append(entry)
            continue
        target = relabel_nav(value, labels) if isinstance(value, list) else value
        relabelled.append({labels.get(label, label): target})
    return relabelled
