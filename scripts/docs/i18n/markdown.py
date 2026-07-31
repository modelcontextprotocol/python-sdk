"""Markdown structure the docs tooling looks at: headings, anchors, fences, spans, links.

This is the one place a heading, an anchor and a code fence are defined, so
the anchor pinning check, the translation validator and the mechanical
repairer cannot disagree about what is a heading, what its `{#id}` block pins,
which anchor rules a heading breaks (`anchor_problems`), or what is code.
Prose-level scans (glossary terms, untranslated runs) must never look inside
code, URLs or HTML tags, so `mask` blanks those regions to same-length
whitespace: positions and line numbers survive, but code can never match a
prose rule. Structural extraction (fences, links, admonitions, tables) works
on the same fence rules so every check agrees on what is code.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import TypeAlias

# A leading YAML front matter block, as MkDocs/Zensical parse it: the closer
# is a line that is exactly `---` or `...` (a `----` line does not end it),
# and the match runs through that line's newline. Shared by the page model
# and the validator so both agree on where the front matter ends.
FRONTMATTER = re.compile(r"\A---[ \t]*\n(?P<body>.*?)^(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.MULTILINE | re.DOTALL)
# An ATX heading, matched the way the docs' markdown parser matches it: one
# to six hashes at column 0 (no leading indent, no space required after
# them), an optional closing hash run that is not part of the text, and
# backslash escapes honoured so an escaped `\#` is text rather than a closer.
HEADING = re.compile(r"^(?P<hashes>#{1,6})(?!#)(?P<text>(?:\\.|[^\\\n])*?)#*[ \t]*$")
# The trailing attr_list block a heading may carry (`Heading {#id .cls}`),
# read with or without the whitespace before it: attr_list only honours a
# block that follows whitespace (a glued `Title{#id}` renders as literal
# text), so the parser sees the id either way and `Heading.attrs_spaced`
# records whether the block would actually render.
HEADING_ATTRS = re.compile(r"[ \t]*\{:?[ \t]*(?P<body>[^}\n]*?)[ \t]*\}[ \t]*$")
# The markdown backslash-escape rule: a backslash before ASCII punctuation
# yields that character. It is also the anchor escape rule — the inline pass
# resolves `{#foo\_bar}` to the id `foo_bar` before attr_list reads the block.
ESCAPE = re.compile(r"\\(?P<char>[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
# An underscore that is not word-internal must be written escaped inside a
# `{#...}` block, or the inline emphasis pass consumes it before attr_list
# sees the block (see `anchor_source_form`).
_BOUNDARY_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")
# The characters a rendered anchor id may use (a plain URL fragment). This is
# the rendered id: its source form may escape an underscore, which resolves back
# to the same id (see `anchor_source_form`).
ANCHOR_ID = re.compile(r"^[A-Za-z0-9_-]+$")
# A code fence opener/closer (``` or ~~~, three or more, possibly indented
# inside a list or admonition). The closer is the same character, at least as
# long as the opener, with nothing but whitespace after it (CommonMark).
_FENCE = re.compile(r"^[ \t]*(?P<run>`{3,}|~{3,})(?P<info>[^\n]*)$")
# Inline code span; cannot cross a blank line, so a stray unpaired backtick
# cannot swallow the paragraphs after it.
CODE_SPAN = re.compile(r"(?s)(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)")
# Inline link/image destinations: `](target "title")`; the whole
# parenthesised part is masked, brackets and label stay prose.
_LINK_DEST = re.compile(r"(?<=\])\((?P<dest>[^)\s]*)(?P<rest>[^)]*)\)")
# A bare URL runs over printable ASCII only (minus the `< > ) ]` that close
# a link): non-ASCII text is prose, so CJK written flush against a URL — no
# space between them in that script — ends the URL instead of being masked
# with it.
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://(?:(?![<>)\]])[!-~])+")
_TAG = re.compile(r"</?[A-Za-z][^>\n]*>|<!--.*?-->", flags=re.DOTALL)
# Every link and image with its label: `!`? `[label](target ...)`.
_LINK = re.compile(r"(?P<image>!?)\[(?P<label>[^\]]*)\]\((?P<target>[^)\s]*)(?P<title>[^)]*)\)")
_HTML_TARGET = re.compile(
    r"""<(?P<tag>a|img)\b[^>]*?\b(?:href|src)=(?P<q>["'])(?P<target>.*?)(?P=q)""", flags=re.IGNORECASE
)


@dataclass(frozen=True)
class Heading:
    """One ATX heading of a page (`line` is its 0-based line index).

    `text` is the heading text with any trailing attr block removed. The
    anchor its `{#...}` block pins (the last `#token`) is carried twice:
    `anchor_source` exactly as written, and `anchor` as the id it renders to
    (markdown escapes resolved). Both are None when the block pins no id.
    `attrs_spaced` is False when the block is written flush against the text
    (`Title{#id}`), the spelling attr_list ignores and prints as text.
    """

    line: int
    level: int
    text: str
    anchor_source: str | None
    anchor: str | None
    attrs_spaced: bool = True


@dataclass(frozen=True)
class MissingAnchor:
    """A heading with no `{#id}` block."""

    heading: Heading


@dataclass(frozen=True)
class MalformedAnchor:
    """A heading whose pinned id uses a character outside `ANCHOR_ID`."""

    heading: Heading


@dataclass(frozen=True)
class UnspacedAnchor:
    """A heading whose `{#id}` block is glued to its text, so it renders as text instead of pinning the id."""

    heading: Heading


@dataclass(frozen=True)
class DuplicateAnchor:
    """A heading pinning an id that an earlier heading of the page (`first`) already pins."""

    heading: Heading
    first: Heading


# One anchor rule a heading breaks; the checks that report anchors only ever
# word these, so they cannot disagree about what the rules are.
AnchorProblem: TypeAlias = MissingAnchor | MalformedAnchor | UnspacedAnchor | DuplicateAnchor


@dataclass(frozen=True)
class Fence:
    """One fenced code block: its info string, the lines it encloses, and whether it was closed."""

    info: str
    body: str
    closed: bool


@dataclass(frozen=True)
class Link:
    """A markdown or HTML link/image target as written in the source."""

    target: str
    image: bool


@dataclass(frozen=True)
class FenceLines:
    """Line indices of one fenced block; an unclosed fence ends at the last line."""

    opener: int
    closer: int
    closed: bool

    @property
    def body(self) -> range:
        """The line indices strictly inside the fence."""
        return range(self.opener + 1, self.closer if self.closed else self.closer + 1)


def fence_line_ranges(lines: list[str]) -> Iterator[FenceLines]:
    """The fenced blocks of `lines`, in order (CommonMark opener/closer rules)."""
    opener: re.Match[str] | None = None
    start = 0
    for index, line in enumerate(lines):
        match = _FENCE.match(line)
        if opener is None:
            # A backtick fence's info string may not itself contain backticks.
            if match and not (match["run"][0] == "`" and "`" in match["info"]):
                opener, start = match, index
            continue
        run = opener["run"]
        if match and match["run"][0] == run[0] and len(match["run"]) >= len(run) and not match["info"].strip():
            yield FenceLines(start, index, closed=True)
            opener = None
    if opener is not None:
        yield FenceLines(start, len(lines) - 1, closed=False)


def mask_fences(lines: list[str]) -> list[str]:
    """The lines with every fenced block's content blanked (fence marker lines kept)."""
    masked = list(lines)
    for fence in fence_line_ranges(lines):
        for index in fence.body:
            masked[index] = ""
    return masked


def unescape(text: str) -> str:
    """Resolve markdown backslash escapes (`\\_` becomes `_`, `\\#` becomes `#`)."""
    return ESCAPE.sub(r"\g<char>", text)


def anchor_source_form(anchor: str) -> str:
    """The rendered id `anchor` as it must be written inside a `{#...}` block.

    Inline emphasis runs over the block before attr_list reads it, so an
    underscore that is not word-internal is escaped: it round-trips to the
    same rendered id instead of turning into emphasis and hiding the block.
    This is the inverse of the escape rule `parse_headings` applies.
    """
    return _BOUNDARY_UNDERSCORE.sub(r"\\_", anchor)


def parse_headings(text: str) -> list[Heading]:
    """The ATX headings of `text`, in order (fence-masked, so a `#` line inside code is not one).

    Each heading's anchor is the rendered id its trailing `{#...}` block pins
    — the last `#token` there with markdown escapes resolved — or None.
    """
    headings: list[Heading] = []
    for line, source in enumerate(mask_fences(text.split("\n"))):
        match = HEADING.match(source)
        if not match:
            continue
        heading_text = match["text"].strip()
        raw: str | None = None
        spaced = True
        if attrs := HEADING_ATTRS.search(heading_text):
            ids = [token[1:] for token in attrs["body"].split() if token.startswith("#") and len(token) > 1]
            raw = ids[-1] if ids else None
            # The block matched with or without leading whitespace; only the
            # spaced spelling is one the renderer reads.
            spaced = attrs.start() == 0 or heading_text[attrs.start()].isspace()
            heading_text = heading_text[: attrs.start()].rstrip()
        anchor = unescape(raw) if raw is not None else None
        headings.append(Heading(line, len(match["hashes"]), heading_text, raw, anchor, spaced))
    return headings


def anchor_problems(headings: Sequence[Heading]) -> list[AnchorProblem]:
    """Every anchor rule the page's headings break, in heading order.

    The rules: a heading must pin an id (`MissingAnchor`), the id may only use
    `ANCHOR_ID` characters (`MalformedAnchor`), its block must follow
    whitespace so the renderer reads it (`UnspacedAnchor`), and no two of the
    page's headings may pin the same well-formed id (`DuplicateAnchor`, naming
    the heading that pinned it first). A heading that breaks an earlier rule
    is not also counted as a duplicate.
    """
    problems: list[AnchorProblem] = []
    first_use: dict[str, Heading] = {}
    for heading in headings:
        if heading.anchor is None:
            problems.append(MissingAnchor(heading))
        elif not ANCHOR_ID.match(heading.anchor):
            problems.append(MalformedAnchor(heading))
        elif not heading.attrs_spaced:
            problems.append(UnspacedAnchor(heading))
        elif heading.anchor in first_use:
            problems.append(DuplicateAnchor(heading, first_use[heading.anchor]))
        else:
            first_use[heading.anchor] = heading
    return problems


def fences(text: str) -> list[Fence]:
    """The fenced code blocks of `text`, in order."""
    lines = text.split("\n")
    found: list[Fence] = []
    for fence in fence_line_ranges(lines):
        match = _FENCE.match(lines[fence.opener])
        assert match is not None
        body = "\n".join(lines[index] for index in fence.body)
        found.append(Fence(info=match["info"].strip(), body=body, closed=fence.closed))
    return found


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each span with same-length whitespace, keeping newlines so lines don't move."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def fence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the fenced blocks (marker lines included, the last line's newline excluded)."""
    lines = text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    return [(offsets[fence.opener], offsets[fence.closer + 1] - 1) for fence in fence_line_ranges(lines)]


def mask_code(text: str) -> str:
    """Blank fenced blocks and inline code spans, keeping the text's length and lines."""
    spans = fence_spans(text)
    masked = _blank(text, spans)
    return _blank(masked, [match.span() for match in CODE_SPAN.finditer(masked)])


def mask(text: str) -> str:
    """Blank everything that is not translatable prose: code, link targets, URLs, HTML tags."""
    masked = mask_code(text)
    spans = [match.span() for pattern in (_LINK_DEST, _URL, _TAG) for match in pattern.finditer(masked)]
    return _blank(masked, spans)


def links(text: str) -> list[Link]:
    """The links and images written in `text`'s prose (code is not scanned)."""
    masked = mask_code(text)
    found = [Link(match["target"], bool(match["image"])) for match in _LINK.finditer(masked)]
    found += [Link(match["target"], match["tag"].lower() == "img") for match in _HTML_TARGET.finditer(masked)]
    return found


def rewrite_link_targets(text: str, transform: Callable[[str], str]) -> str:
    """Replace each prose link/image target with `transform(target)` (code is not touched).

    The targets offered are exactly the ones `links` reports, markdown and
    HTML alike; a target `transform` returns unchanged stays as written.
    """
    masked = mask_code(text)
    edits: list[tuple[int, int, str]] = []
    for pattern in (_LINK, _HTML_TARGET):
        for match in pattern.finditer(masked):
            start, end = match.span("target")
            if (rewritten := transform(text[start:end])) != text[start:end]:
                edits.append((start, end, rewritten))
    parts: list[str] = []
    cursor = 0
    for start, end, rewritten in sorted(edits):
        parts += [text[cursor:start], rewritten]
        cursor = end
    return "".join([*parts, text[cursor:]])
