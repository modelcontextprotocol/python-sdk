"""Tests for the page block model and the translatable page set (i18n/pages.py)."""

from typing import Any

from i18n.pages import Block, block_hashes, block_salt, page_text, split_blocks, translatable_pages

PAGE = """\
---
title: Tools
---

# Tools {#tools}

Intro text.

## First {#first}

```python
## not a heading
```

Body one.

## Second {#second}

Body two.
"""


def test_split_blocks_page_with_front_matter_and_sections_tiles_exactly() -> None:
    blocks = split_blocks(PAGE)

    assert [block.kind for block in blocks] == ["frontmatter", "top", "section", "section"]
    assert page_text(blocks) == PAGE
    # The blank line above a `##` heading belongs to that section, not the one before it.
    assert blocks[1].text == "\n# Tools {#tools}\n\nIntro text.\n"
    assert blocks[2].text.startswith("\n## First {#first}\n")
    assert "## not a heading" in blocks[2].text


def test_split_blocks_page_opening_with_section_has_no_top_block() -> None:
    blocks = split_blocks("## Only {#only}\n\nBody.\n")

    assert [block.kind for block in blocks] == ["section"]
    assert page_text(blocks) == "## Only {#only}\n\nBody.\n"


def test_split_blocks_page_without_trailing_newline_round_trips() -> None:
    text = "# Title {#t}\n\ntext"

    assert page_text(split_blocks(text)) == text


def test_appending_a_section_leaves_the_earlier_blocks_unchanged() -> None:
    before = split_blocks("# T {#t}\n\nIntro.\n\n## A {#a}\n\nA body.\n\n## B {#b}\n\nB body.\n")
    after = split_blocks("# T {#t}\n\nIntro.\n\n## A {#a}\n\nA body.\n\n## B {#b}\n\nB body.\n\n## C {#c}\n\nC body.\n")

    assert after[: len(before)] == before
    assert after[-1].text == "\n## C {#c}\n\nC body.\n"


def test_front_matter_only_ends_at_a_bare_terminator_line() -> None:
    frontmatter, top = split_blocks("---\ntitle: T\n----\n---\nbody\n")

    assert frontmatter.text == "---\ntitle: T\n----\n---\n"
    assert top.text == "body\n"


def test_block_labels_name_the_block_for_prompts() -> None:
    frontmatter, top, section = split_blocks("---\ntitle: T\n---\nintro\n\n## Sec {#s}\nbody\n")

    assert frontmatter.label == "front matter"
    assert top.label == "introduction (before the first `##` heading)"
    assert section.text.startswith("\n") and section.label == "## Sec {#s}"


def test_block_hashes_change_when_the_salt_changes() -> None:
    blocks = [Block("top", "same text\n")]

    plain = block_hashes(blocks, block_salt("g", "i", "1"))
    salted = block_hashes(blocks, block_salt("g", "i", "2"))

    assert plain != salted
    assert plain == block_hashes(blocks, block_salt("g", "i", "1"))


def test_translatable_pages_walks_the_nav_and_applies_exclusions() -> None:
    nav: list[Any] = [
        {"Home": "index.md"},
        {"Guide": ["guide/index.md", {"Deep": "guide/deep.md"}]},
        {"Site": "https://example.org/"},
        {"Migration": "migration.md"},
        {"API Reference": "api/"},
    ]

    pages = translatable_pages(nav, ["migration.md", "api/**"])

    assert pages == ["index.md", "guide/index.md", "guide/deep.md"]
