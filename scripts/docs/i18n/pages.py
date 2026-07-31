"""The translatable page set and the block model of a page.

The set of pages a language site translates is exactly the `mkdocs.yml`
navigation minus the registry's exclusions — the same list the docs build
publishes, so a page added to the nav is a page every language is missing.

A page is a sequence of blocks: its front matter, the text before the first
`##` heading, then one block per `##` section. Blocks are the unit of
hashing, incremental retranslation, validation findings and repair, and they
tile the page exactly (joining a page's blocks reproduces its bytes).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

# scripts/docs is the import root: the nav walker is shared with the build's
# config generator, which imports it the same way.
from navigation import nav_pages

from i18n.markdown import FRONTMATTER, parse_headings

BlockKind = Literal["frontmatter", "top", "section"]

# Bumped whenever the translation pipeline changes in a way that should
# invalidate every stored translation (prompt structure, block model, ...).
PIPELINE_VERSION = "1"

# A block boundary is a level-2 (`##`) heading, as the shared parser sees one.
SECTION_LEVEL = 2


@dataclass(frozen=True)
class Block:
    """One block of a page; `text` is its exact source, surrounding newlines included."""

    kind: BlockKind
    text: str

    @property
    def label(self) -> str:
        """A human-readable name for the block, used in prompts and findings."""
        if self.kind == "frontmatter":
            return "front matter"
        if self.kind == "top":
            return "introduction (before the first `##` heading)"
        return self.text.lstrip("\n").split("\n", 1)[0].strip()


def split_blocks(text: str) -> list[Block]:
    """Split a page into its blocks; `page_text(split_blocks(text)) == text`.

    The blank line(s) separating a `##` section from what precedes it belong
    to that section, so a block's bytes never depend on the block after it —
    appending or deleting a section leaves every other block, and its hash,
    untouched.
    """
    blocks: list[Block] = []
    body = text
    if match := FRONTMATTER.match(text):
        blocks.append(Block("frontmatter", match.group(0)))
        body = text[match.end() :]

    lines = body.split("\n")
    headings = [heading.line for heading in parse_headings(body) if heading.level == SECTION_LEVEL]
    starts = [_leading_blanks(lines, index) for index in headings]
    # The introduction is everything before the first section's separator; a
    # body that opens with a section (or is empty) has none.
    top = ("\n".join(lines[: starts[0]]) + "\n" if starts[0] else "") if starts else body
    if top:
        blocks.append(Block("top", top))
    for position, start in enumerate(starts):
        last = position == len(starts) - 1
        end = len(lines) if last else starts[position + 1]
        blocks.append(Block("section", "\n".join(lines[start:end]) + ("" if last else "\n")))
    return blocks


def _leading_blanks(lines: list[str], heading: int) -> int:
    """The line where a section starts: its `##` line plus the blank lines just above it."""
    start = heading
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    return start


def page_text(blocks: Iterable[Block]) -> str:
    """Reassemble a page from its blocks (the inverse of `split_blocks`)."""
    return "".join(block.text for block in blocks)


def sha256(data: str) -> str:
    """The hex sha256 of a string's UTF-8 bytes."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def block_salt(general_prompt_hash: str, instructions_hash: str, glossary_hash: str) -> str:
    """The salt mixed into every block hash: any prompt input changing changes every hash."""
    return f"pipeline={PIPELINE_VERSION}\n{general_prompt_hash}\n{instructions_hash}\n{glossary_hash}\n"


def block_hashes(blocks: Iterable[Block], salt: str) -> list[str]:
    """The salted hash of each block, in order."""
    return [sha256(salt + block.text) for block in blocks]


def translatable_pages(nav: list[Any], exclude_pages: Iterable[str]) -> list[str]:
    """The prose pages the language sites translate, in nav order.

    A pattern ending in `/**` excludes a whole subtree; any other pattern is an
    exact page path.
    """
    excluded: list[str] = []
    prefixes: list[str] = []
    for pattern in exclude_pages:
        if pattern.endswith("/**"):
            prefixes.append(pattern.removesuffix("**"))
        else:
            excluded.append(pattern)
    return [
        page
        for page in nav_pages(nav)
        if page.endswith(".md") and page not in excluded and not any(page.startswith(p) for p in prefixes)
    ]
