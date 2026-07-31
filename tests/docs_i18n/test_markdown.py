"""Tests for markdown masking and structure extraction (i18n/markdown.py)."""

from pathlib import Path

from check_anchors import check_pages

from i18n.glossary import Glossary
from i18n.markdown import (
    DuplicateAnchor,
    Heading,
    MalformedAnchor,
    MissingAnchor,
    UnspacedAnchor,
    anchor_problems,
    anchor_source_form,
    fences,
    links,
    mask,
    mask_code,
    mask_fences,
    parse_headings,
    rewrite_link_targets,
)
from i18n.translate import mechanical_repair
from i18n.validate import validate_page, validate_page_standalone

TILDE_PAGE: str = """\
Intro with `inline` code and a [link](guide.md).

~~~~text
``` backticks inside a tilde fence are just content
~~~~

```python
url = "https://example.org/inside-code"
"""


def test_mask_code_blanks_fences_and_spans_but_keeps_length_and_lines() -> None:
    masked = mask_code(TILDE_PAGE)

    assert len(masked) == len(TILDE_PAGE)
    assert masked.count("\n") == TILDE_PAGE.count("\n")
    assert "inline" not in masked
    assert "backticks inside" not in masked
    assert "https://example.org/inside-code" not in masked
    assert "[link](guide.md)" in masked


def test_mask_removes_link_targets_urls_and_html_but_keeps_prose() -> None:
    text = "See [the guide](guide.md#anchor) at https://example.org and <b>bold</b> words.\n"

    masked = mask(text)

    assert "the guide" in masked
    assert "guide.md" not in masked
    assert "https://" not in masked
    assert "<b>" not in masked and "bold" in masked


def test_mask_ends_a_bare_url_at_cjk_text_written_flush_against_it() -> None:
    # CJK prose puts no space after a URL, so the URL must not swallow the sentence (and its terms).
    text = "詳細はhttps://spec.example.ioを参照してください。MCPサーバーは便利です。\n"

    masked = mask(text)

    assert "https://spec.example.io" not in masked
    assert "を参照してください。MCPサーバーは便利です。" in masked
    assert masked.count("MCP") == 1 and len(masked) == len(text)


def test_fences_report_info_strings_and_bodies_including_unclosed_fence() -> None:
    found = fences(TILDE_PAGE)

    assert [fence.info for fence in found] == ["text", "python"]
    assert found[0].body == "``` backticks inside a tilde fence are just content"
    assert found[1].body == 'url = "https://example.org/inside-code"\n'


def test_mask_fences_keeps_marker_lines_and_blanks_bodies() -> None:
    lines = TILDE_PAGE.split("\n")

    masked = mask_fences(lines)

    assert masked[2] == "~~~~text" and masked[3] == "" and masked[4] == "~~~~"
    assert len(masked) == len(lines)


def test_links_finds_markdown_and_html_targets_outside_code_only() -> None:
    text = (
        'A [page](tools.md), an ![image](img/a.png), <a href="https://x.example/">html</a>,'
        " and `not a [link](hidden.md)`.\n\n```\n[fenced](gone.md)\n```\n"
    )

    found = {(link.target, link.image) for link in links(text)}

    assert found == {("tools.md", False), ("img/a.png", True), ("https://x.example/", False)}


def test_rewrite_link_targets_replaces_prose_targets_and_leaves_code_untouched() -> None:
    text = (
        'A [page](tools.md#h), an ![image](img/a.png), <a href="tools.md">html</a>,'
        " and `not a [link](tools.md)`.\n\n```\n[fenced](tools.md)\n```\n"
    )

    rewritten = rewrite_link_targets(text, lambda target: target.replace("tools.md", "moved.md"))

    assert rewritten == text.replace("](tools.md#h)", "](moved.md#h)").replace('href="tools.md"', 'href="moved.md"')


def test_parse_headings_reads_level_text_and_anchor_and_skips_fenced_lines() -> None:
    page = "# Title {#title}\n\nprose\n\n```md\n## not a heading {#nope}\n```\n\n### Deep ##\n\n##Tight {#tight}\n"

    headings = parse_headings(page)

    assert headings == [
        Heading(line=0, level=1, text="Title", anchor_source="title", anchor="title"),
        Heading(line=8, level=3, text="Deep", anchor_source=None, anchor=None),
        Heading(line=10, level=2, text="Tight", anchor_source="tight", anchor="tight"),
    ]


def test_anchor_escape_rule_maps_source_and_rendered_forms_to_each_other() -> None:
    (heading,) = parse_headings("## `_meta`: for the app {#\\_meta-for-the-app}")

    assert (heading.anchor_source, heading.anchor) == ("\\_meta-for-the-app", "_meta-for-the-app")
    assert anchor_source_form("_meta-for-the-app") == "\\_meta-for-the-app"
    # A word-internal underscore is never escaped.
    assert anchor_source_form("reconnecting-with-prior_discover") == "reconnecting-with-prior_discover"


def test_a_glued_cjk_anchor_block_is_read_then_repaired_to_the_canonical_spaced_form() -> None:
    """A model writes CJK headings with no space before the attr block; attr_list would print that block as
    text, so the parser still sees the pinned id and the repair rewrites the heading to `## text {#id}`."""
    (heading,) = parse_headings("## ツール{#tools}")
    assert (heading.text, heading.anchor, heading.attrs_spaced) == ("ツール", "tools", False)

    english = "## Tools {#tools}\n\nBody.\n"
    repaired = mechanical_repair(english, "## ツール{#tools}\n\n本文。\n")

    assert repaired == "## ツール {#tools}\n\n本文。\n"
    assert validate_page("t.md", english, repaired, Glossary((), ()), script="cjk") == []


def test_the_anchor_check_and_the_validator_report_the_same_anchor_problems(tmp_path: Path) -> None:
    """The anchor rules (unpinned heading, disallowed id characters, a block glued to the text, an id reused
    on the page) are one shared detection; the source-page check and the standalone validator only word its
    problems differently."""
    text = "# T {#t}\n\n## A {#same}\n\n## B {#same}\n\n## C {#bad!}\n\n## D{#glued}\n\n## E\n"

    problems = anchor_problems(parse_headings(text))
    assert [(type(problem), problem.heading.line + 1) for problem in problems] == [
        (DuplicateAnchor, 5),
        (MalformedAnchor, 7),
        (UnspacedAnchor, 9),
        (MissingAnchor, 11),
    ]

    page = tmp_path / "docs" / "guide.md"
    page.parent.mkdir()
    page.write_text(text, encoding="utf-8")
    assert check_pages([page], docs=page.parent) == (
        6,
        [
            "docs/guide.md:5: #same already anchors line 3",
            'docs/guide.md:7: #bad! may only use letters, digits, "_", "-"',
            "docs/guide.md:9: {#glued} must follow a space, or the block renders as heading text",
            "docs/guide.md:11: heading has no {#anchor}: 'E'",
        ],
    )
    findings = validate_page_standalone("guide.md", text)
    assert [str(finding) for finding in findings] == [
        "guide.md [headings] heading on line 5 reuses the anchor of line 3",
        "guide.md [headings] heading on line 7 anchor {#bad!} uses characters outside A-Za-z0-9_-",
        "guide.md [headings] heading on line 9 anchor {#glued} must follow a space",
        "guide.md [headings] heading on line 11 has no {#anchor}",
    ]


def test_an_escaped_underscore_anchor_reads_the_same_to_the_check_the_validator_and_the_repair(
    tmp_path: Path,
) -> None:
    """The escape rule is defined once: the anchor check accepts the source spelling, the validator reads
    the rendered id however the translation spells it, and the repair re-imposes that one source spelling."""
    english = "# `_meta`: for the application {#\\_meta-for-the-application}\n\nUse it.\n"
    page = tmp_path / "docs" / "meta.md"
    page.parent.mkdir()
    page.write_text(english, encoding="utf-8")
    assert check_pages([page], docs=page.parent) == (1, [])

    escaped = "# `_meta`: fuer die Anwendung {#\\_meta-for-the-application}\n\nBenutze es.\n"
    plain = escaped.replace("\\_meta-for", "_meta-for")
    for translated in (escaped, plain):
        assert validate_page("meta.md", english, translated, Glossary((), ()), script="latin") == []

    assert mechanical_repair(english, plain) == escaped
