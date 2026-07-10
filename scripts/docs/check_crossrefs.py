"""Fail the docs build when a page's cross-references did not resolve.

Zensical (0.0.48) stays green even under `--strict` on two failure modes
MkDocs strict mode aborted on:

- An unresolvable `[text][identifier]` cross-reference renders as literal
  bracket text (mkdocs-autorefs used to warn). The generated API index and
  the docstring cross-references rely on such references resolving.
- A failed `objects.inv` inventory download is logged as an ERROR record and
  otherwise ignored, silently degrading every link through that inventory
  (thousands of standard-library links alone) to plain text.

Both are caught from the built site itself, so no log-wording change can
disarm the check: an unresolved reference leaves a tell-tale bracket
sequence in prose text (code blocks legitimately contain `][`, e.g. dict
indexing, so only text outside `<pre>`/`<code>` counts), and every inventory
declared in `mkdocs.yml` must contribute at least one resolved reference —
an `autorefs-external` anchor, which hand-authored prose links to the same
host never carry — to the site (an inventory that contributes none is dead
config and fails too).

Offline contributors can skip the inventory check by setting
`DOCS_ALLOW_INVENTORY_FAILURE=1`; CI (`CI=true`) never skips it.

Usage:
    python scripts/docs/check_crossrefs.py --site-dir site
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).parent.parent.parent

# Unresolved cross-reference tell-tales in extracted prose (`\x00` marks a
# skipped code element, see _ProseTextExtractor): the two-part
# `[text][identifier]` reconstruction — the identifier part is always plain
# text, so a code mark inside the second brackets means indexing prose like
# `data[`x`][`y`]`, not a reference — and the shortcut `[`identifier`]` form,
# which extracts as `[\x00]` unless a preceding word character or bracket
# makes it a subscript like `list[`str`]`.
_UNRESOLVED = re.compile(r"\]\[[^\]\s\x00]*\]|(?<![\w\]\x00])\[\x00\]")

# An inventory-resolved reference renders as an anchor with the
# `autorefs-external` class; a hand-authored prose link to the same host has
# no autorefs class and must not satisfy the inventory check.
_EXTERNAL_REF = re.compile(r"<a\s[^>]*autorefs-external[^>]*>")


class _ProseTextExtractor(HTMLParser):
    """Collect text outside <pre>/<code>/<script>/<style> elements.

    A skipped element leaves a `\\x00` mark and every other tag boundary
    breaks the text with a newline, so bracket sequences cannot be
    synthesized by joining text from unrelated elements (`x]</td><td>[y`)
    while sequences genuinely adjacent in one text node stay intact. A
    block-level tag resets the skip state, so an unclosed inline `<code>`
    in authored raw HTML cannot hide the rest of the page.
    """

    _SKIP = frozenset({"pre", "code", "script", "style"})
    _BLOCK = frozenset(
        {"article", "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section", "table", "td", "th"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            if not self._skip_depth:
                self.chunks.append("\x00")
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._skip_depth = 0
            self.chunks.append("\n")
        elif not self._skip_depth:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
        elif not self._skip_depth:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def unresolved_refs(html: str) -> list[str]:
    """Return the unresolved cross-reference fragments rendered in `html`."""
    parser = _ProseTextExtractor()
    parser.feed(html)
    return [fragment.replace("\x00", "<code>") for fragment in _UNRESOLVED.findall("".join(parser.chunks))]


def _inventory_origins() -> set[str]:
    """The scheme+host origins of the inventories declared in mkdocs.yml."""
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    for plugin in config["plugins"]:
        if isinstance(plugin, dict) and "mkdocstrings" in plugin:
            inventories = plugin["mkdocstrings"]["handlers"]["python"].get("inventories", [])
            return {_origin(entry["url"] if isinstance(entry, dict) else entry) for entry in inventories}
    return set()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", default="site", help="The built site directory to scan.")
    args = parser.parse_args()

    unlinked = _inventory_origins()
    failures: list[str] = []
    for page in sorted(Path(args.site_dir).rglob("*.html")):
        html = page.read_text(encoding="utf-8")
        if unlinked and "autorefs-external" in html:
            for tag in _EXTERNAL_REF.finditer(html):
                unlinked -= {origin for origin in unlinked if f'href="{origin}' in tag.group(0)}
        # Both tell-tales have a literal signature in the raw HTML ("][" for
        # the two-part form, "[<code" for the shortcut form); skip the parse
        # for the majority of pages that contain neither.
        if "][" in html or "[<code" in html:
            failures.extend(f"{page}: {fragment}" for fragment in unresolved_refs(html))
    if failures:
        print("error: unresolved cross-references rendered as literal text:", file=sys.stderr)
        print("\n".join(failures[:20]), file=sys.stderr)
        raise SystemExit(1)
    offline_ok = os.environ.get("DOCS_ALLOW_INVENTORY_FAILURE") == "1" and os.environ.get("CI") != "true"
    if unlinked and not offline_ok:
        print(
            "error: no page links into these declared inventories (download failed, or dead"
            " inventory config?): " + ", ".join(sorted(unlinked)),
            file=sys.stderr,
        )
        print("set DOCS_ALLOW_INVENTORY_FAILURE=1 to build offline", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
