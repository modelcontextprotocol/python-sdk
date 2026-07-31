"""The structural validator: prove a translation kept the English page's shape.

The model translates prose but must reproduce everything that is machinery
byte-for-byte — headings and their pinned anchors, code fences, links,
admonition and tab syntax, tables — and must honour the glossary. Each check
compares the translated page against the current English source block by
block, so a failure names the block that broke and can be fed straight back
into a repair prompt. Scans that look at prose run on masked text (code,
URLs and tags blanked) so code can never trip a prose rule. The nav-label
map gets the same glossary discipline over its label pairs.

A translation whose English page or prompt inputs have since changed cannot
be measured against them (it was made before they changed), so
`validate_page_standalone` carries only the well-formedness a page must have
by itself — the checks that read the translation and nothing else.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from i18n.config import Script
from i18n.glossary import Glossary
from i18n.markdown import (
    FRONTMATTER,
    AnchorProblem,
    MalformedAnchor,
    MissingAnchor,
    UnspacedAnchor,
    anchor_problems,
    fences,
    links,
    mask,
    mask_fences,
    parse_headings,
)
from i18n.pages import Block, split_blocks

_FRONTMATTER_KEY = re.compile(r"^(?P<key>[A-Za-z0-9_-]+):(?P<value>.*)$")
# A page that opens a front matter block; `FRONTMATTER` matching it means it closes.
_FRONTMATTER_OPEN = re.compile(r"\A---[ \t]*\n")
_ADMONITION = re.compile(r"^[ \t]*(?P<marker>!!!|\?\?\?\+?)[ \t]+(?P<kind>[\w-]+)")
_TAB = re.compile(r"^[ \t]*===[ \t]+")
_DETAILS = re.compile(r"<(?P<tag>details|summary)\b", flags=re.IGNORECASE)
_SNIPPET = re.compile(r"--8<--")
_TABLE_ROW = re.compile(r"^[ \t]*\|")
# Markers a model emits in prose when it gives up part-way through a page
# (scanned on masked prose so code can never trip them).
_PROSE_PLACEHOLDERS = (
    re.compile(r"\[\s*(?:translation|rest of|remaining)[^\]]*\]", re.IGNORECASE),
    re.compile(r"\((?:content )?omitted[^)]*\)", re.IGNORECASE),
    re.compile(r"\[\s*\.\.\.\s*\]"),
)
# The same abridgement written as an HTML comment. Masking blanks comments as
# it does tags, so these are matched on the raw comments, never on prose.
_COMMENT = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
_ABRIDGED = re.compile(r"\b(?:omitted|continues|truncated|abridged|remaining|rest of)\b", re.IGNORECASE)

# Fifteen Latin words in a row (glossary keep-terms removed first) in a page
# for a non-Latin-script language is a passage the model left in English, not
# a stray loanword. Whether the check applies is the target language's script,
# never the block's own character mix: an untranslated block is all-Latin,
# which is exactly the case the check exists to catch.
_LATIN_RUN = re.compile(r"(?:[A-Za-z]+(?:[-'][A-Za-z]+)*[\s,;:.!?()\"]+){14}[A-Za-z]+")

# An English keep-term with a trailing plural `s` or possessive `'s` is the
# same token as the bare term, on both sides: a language may keep or drop the
# English plural marker (Korean and Chinese conventionally drop it) without a
# parity mismatch.
_TERM_SUFFIX = r"(?:['’]s|s)?"

# Front matter values that are prose and may differ between languages.
TRANSLATABLE_FRONTMATTER = frozenset({"title"})


@dataclass(frozen=True)
class Finding:
    """One structural discrepancy; `block` is the index into `split_blocks`, or None for page-level."""

    page: str
    block: int | None
    check: str
    message: str

    def __str__(self) -> str:
        where = "" if self.block is None else f" block {self.block}"
        return f"{self.page}{where} [{self.check}] {self.message}"


@dataclass(frozen=True)
class _Heading:
    level: int
    anchor: str | None


def validate_page(
    page: str,
    english: str,
    translated: str,
    glossary: Glossary,
    *,
    script: Script,
    translatable_frontmatter: frozenset[str] = TRANSLATABLE_FRONTMATTER,
) -> list[Finding]:
    """Every structural finding for one translated page (an empty list means it passes).

    `script` is the target language's writing system: the untranslated-English
    scan runs for every non-Latin-script language.
    """
    findings: list[Finding] = []
    source_blocks, output_blocks = split_blocks(english), split_blocks(translated)
    if _shape(source_blocks) != _shape(output_blocks):
        findings.append(
            Finding(
                page,
                None,
                "blocks",
                f"expected the page's blocks to be {_shape(source_blocks)}, found {_shape(output_blocks)}"
                " (a block is the front matter, the introduction, or one `##` section, in that order)",
            )
        )
        pairs: list[tuple[int | None, str, str]] = [(None, english, translated)]
    else:
        pairs = [
            (index, source.text, output.text)
            for index, (source, output) in enumerate(zip(source_blocks, output_blocks, strict=True))
        ]
    for block, source, output in pairs:
        for check, message in _check_block(source, output, glossary, script, translatable_frontmatter):
            findings.append(Finding(page, block, check, message))
    return findings


def validate_page_standalone(page: str, translated: str) -> list[Finding]:
    """Every finding a translated page yields on its own, with no English to compare against.

    A page that is outdated is checked this way. The English it was made
    from, and possibly the glossary and instructions too, have moved on, and
    exactly that is why it is outdated: enforcing today's glossary against
    yesterday's translation would fail the gate until a fresh translation run
    landed. What it must still hold by itself is well-formedness — the front
    matter closes, every code fence closes, and every heading pins a distinct,
    well-formed anchor.
    """
    findings = [Finding(page, None, "frontmatter", message) for message in _frontmatter_closes(translated)]
    findings += [Finding(page, None, "headings", message) for message in _anchor_syntax(translated)]
    for index, block in enumerate(split_blocks(translated)):
        findings += [Finding(page, index, "code", message) for message in _fences_closed(block.text)]
    return findings


def _shape(blocks: list[Block]) -> list[str]:
    """The block kinds of a page, e.g. `["top", "section", "section"]`."""
    return [block.kind for block in blocks]


def _check_block(
    source: str, output: str, glossary: Glossary, script: Script, translatable_frontmatter: frozenset[str]
) -> list[tuple[str, str]]:
    """The `(check, message)` findings for one aligned block pair."""
    findings: list[tuple[str, str]] = []
    findings += [("frontmatter", msg) for msg in _frontmatter(source, output, translatable_frontmatter)]
    findings += [("headings", msg) for msg in _headings(source, output)]
    findings += [("code", msg) for msg in _code(source, output)]
    findings += [("syntax", msg) for msg in _syntax(source, output)]
    findings += [("tables", msg) for msg in _tables(source, output)]
    findings += [("links", msg) for msg in _links(source, output)]
    findings += [("glossary", msg) for msg in _glossary(source, output, glossary)]
    findings += [("completeness", msg) for msg in _completeness(output, glossary, script)]
    return findings


def _frontmatter(source: str, output: str, translatable: frozenset[str]) -> list[str]:
    expected, found = _frontmatter_fields(source), _frontmatter_fields(output)
    if [key for key, _ in expected] != [key for key, _ in found]:
        return [f"front matter keys are {[key for key, _ in found]}, expected {[key for key, _ in expected]}"]
    return [
        f"front matter value of `{key}` changed but must be copied verbatim"
        for (key, want), (_, got) in zip(expected, found, strict=True)
        if key not in translatable and want != got
    ]


def _frontmatter_fields(text: str) -> list[tuple[str, str]]:
    match = FRONTMATTER.match(text)
    if match is None:
        return []
    fields = (_FRONTMATTER_KEY.match(line) for line in match["body"].split("\n"))
    return [(field["key"], field["value"].strip()) for field in fields if field]


def _frontmatter_closes(text: str) -> list[str]:
    """An opening `---` front matter line must have its closing terminator line."""
    if _FRONTMATTER_OPEN.match(text) and FRONTMATTER.match(text) is None:
        return ["front matter opens with `---` but never closes (add the terminating `---` line)"]
    return []


def _headings(source: str, output: str) -> list[str]:
    expected, found = _heading_list(source), _heading_list(output)
    if len(expected) != len(found):
        return [f"page has {len(found)} headings, expected {len(expected)}"]
    messages: list[str] = []
    for index, (want, got) in enumerate(zip(expected, found, strict=True), start=1):
        if want.level != got.level:
            messages.append(f"heading {index} is level {got.level}, expected level {want.level}")
        if want.anchor != got.anchor:
            messages.append(f"heading {index} anchor is {_anchor_repr(got.anchor)}, expected {{#{want.anchor}}}")
    return messages


def _anchor_repr(anchor: str | None) -> str:
    return "missing" if anchor is None else f"{{#{anchor}}}"


def _heading_list(text: str) -> list[_Heading]:
    return [_Heading(heading.level, heading.anchor) for heading in parse_headings(text)]


def _anchor_syntax(text: str) -> list[str]:
    """Every heading must pin a well-formed anchor id, and no two headings the same one."""
    return [_anchor_message(problem) for problem in anchor_problems(parse_headings(text))]


def _anchor_message(problem: AnchorProblem) -> str:
    """One shared anchor problem, worded for a translated page (headings named by line)."""
    line = problem.heading.line + 1
    if isinstance(problem, MissingAnchor):
        return f"heading on line {line} has no {{#anchor}}"
    if isinstance(problem, MalformedAnchor):
        return f"heading on line {line} anchor {{#{problem.heading.anchor}}} uses characters outside A-Za-z0-9_-"
    if isinstance(problem, UnspacedAnchor):
        return f"heading on line {line} anchor {{#{problem.heading.anchor}}} must follow a space"
    return f"heading on line {line} reuses the anchor of line {problem.first.line + 1}"


def _fences_closed(text: str) -> list[str]:
    """Every code fence a translation opens must close, or the rest of the page is swallowed as code."""
    return [
        f"code block {index} is not closed (add its closing fence marker)"
        for index, fence in enumerate(fences(text), start=1)
        if not fence.closed
    ]


def _code(source: str, output: str) -> list[str]:
    expected, found = fences(source), fences(output)
    if len(expected) != len(found):
        return [f"page has {len(found)} fenced code blocks, expected {len(expected)}"]
    messages: list[str] = []
    for index, (want, got) in enumerate(zip(expected, found, strict=True), start=1):
        if want.info != got.info:
            messages.append(f"code block {index} info string is {got.info!r}, expected {want.info!r}")
        elif want.closed and not got.closed:
            messages.append(f"code block {index} is not closed (add its closing fence marker)")
        elif want.body != got.body:
            messages.append(f"code block {index} ({want.info or 'plain'}) content differs from the English source")
    source_snippets = [line.strip() for line in source.split("\n") if _SNIPPET.search(line)]
    output_snippets = [line.strip() for line in output.split("\n") if _SNIPPET.search(line)]
    if source_snippets != output_snippets:
        messages.append(f"`--8<--` include lines are {output_snippets}, expected {source_snippets}")
    return messages


def _syntax(source: str, output: str) -> list[str]:
    """Admonition markers/types, content-tab count, and details/summary tags must all match."""
    messages: list[str] = []
    if (want := _admonitions(source)) != (got := _admonitions(output)):
        messages.append(f"admonition markers are {got}, expected {want} (translate the title, not the marker or type)")
    want_tabs, got_tabs = _count_lines(source, _TAB), _count_lines(output, _TAB)
    if want_tabs != got_tabs:
        messages.append(f"page has {got_tabs} content tabs (`===`), expected {want_tabs}")
    want_details = Counter(match["tag"].lower() for match in _DETAILS.finditer(source))
    got_details = Counter(match["tag"].lower() for match in _DETAILS.finditer(output))
    if want_details != got_details:
        messages.append(f"HTML details/summary tags are {dict(got_details)}, expected {dict(want_details)}")
    return messages


def _admonitions(text: str) -> list[str]:
    matches = (_ADMONITION.match(line) for line in mask_fences(text.split("\n")))
    return [f"{match['marker']} {match['kind']}" for match in matches if match]


def _count_lines(text: str, pattern: re.Pattern[str]) -> int:
    return sum(1 for line in mask_fences(text.split("\n")) if pattern.match(line))


def _tables(source: str, output: str) -> list[str]:
    want, got = _table_shapes(source), _table_shapes(output)
    if want == got:
        return []
    return [f"table shapes (rows x columns) are {got}, expected {want}"]


def _table_shapes(text: str) -> list[tuple[int, int]]:
    """`(rows, columns)` of each table; consecutive `|` lines form one table."""
    shapes: list[tuple[int, int]] = []
    rows: list[str] = []
    for line in [*mask_fences(text.split("\n")), ""]:
        if _TABLE_ROW.match(line):
            rows.append(line)
        elif rows:
            columns = max(len(row.strip().strip("|").split("|")) for row in rows)
            shapes.append((len(rows), columns))
            rows = []
    return shapes


def _links(source: str, output: str) -> list[str]:
    expected = Counter((link.target, link.image) for link in links(source))
    found = Counter((link.target, link.image) for link in links(output))
    if expected == found:
        return []
    messages: list[str] = []
    if missing := expected - found:
        messages.append(f"missing link targets {_targets(missing)}")
    if added := found - expected:
        messages.append(f"unexpected link targets {_targets(added)}")
    return messages


def _targets(counter: Counter[tuple[str, bool]]) -> list[str]:
    return sorted(f"{'image ' if image else ''}{target} x{count}" for (target, image), count in counter.items())


def validate_nav_labels(
    page: str,
    labels: Sequence[str],
    translated: Mapping[str, str],
    glossary: Glossary,
    *,
    exact_keys: bool = True,
) -> list[Finding]:
    """Every finding for a translated nav-label map (an empty list means it passes).

    `labels` is the English list the map should cover. With `exact_keys` the
    map must key exactly those labels; without it (an existing map checked
    offline), labels it lacks are simply not translated yet and its extra
    entries are stale, so only the renderings it does hold are checked.
    """
    findings: list[Finding] = []
    if exact_keys:
        if missing := [label for label in labels if label not in translated]:
            findings.append(Finding(page, None, "labels", f"missing renderings for the labels {missing}"))
        if extra := [label for label in translated if label not in set(labels)]:
            findings.append(Finding(page, None, "labels", f"unexpected labels {extra} (keep the English keys exactly)"))
    for label in labels:
        if (rendering := translated.get(label)) is None:
            continue
        for check, message in _check_label(label, rendering, glossary):
            findings.append(Finding(page, None, check, message))
    return findings


def _check_label(label: str, rendering: str, glossary: Glossary) -> list[tuple[str, str]]:
    """The `(check, message)` findings for one English label and its rendering."""
    if not rendering.strip():
        return [("labels", f"the rendering of {label!r} is empty")]
    findings: list[tuple[str, str]] = []
    for term, banned in glossary.enforced_avoids:
        if banned in rendering:
            findings.append(("glossary", f"banned rendering {banned!r} of {term!r} appears in {label!r}"))
    for term in glossary.keep_in_source_language:
        want, got = _count_term(label, term), _count_term(rendering, term)
        if want != got:
            findings.append(
                ("glossary", f"{term!r} must appear verbatim {want} time(s) as in the label {label!r}, found {got}")
            )
    return findings


def _glossary(source: str, output: str, glossary: Glossary) -> list[str]:
    output_prose = mask(output)
    messages = _avoid_renderings(output_prose, glossary)
    source_prose = mask(source)
    for term in glossary.keep_in_source_language:
        want, got = _count_term(source_prose, term), _count_term(output_prose, term)
        if want != got:
            messages.append(f"{term!r} must appear verbatim {want} time(s) as in the English block, found {got}")
    return messages


def _avoid_renderings(prose: str, glossary: Glossary) -> list[str]:
    """No banned glossary rendering may appear in the (already-masked) prose."""
    return [
        f"banned rendering {banned!r} of {term!r} appears; use the glossary target instead"
        for term, banned in glossary.enforced_avoids
        if banned in prose
    ]


def _term_pattern(term: str) -> re.Pattern[str]:
    """A case-sensitive whole-word `term`, its English plural `s`/possessive `'s` included in the token."""
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}{_TERM_SUFFIX}(?![A-Za-z0-9_])")


def _count_term(prose: str, term: str) -> int:
    """Whole-word occurrences of `term` (plural or possessive form included) in already-masked prose."""
    return len(_term_pattern(term).findall(prose))


def _completeness(output: str, glossary: Glossary, script: Script) -> list[str]:
    prose = mask(output)
    placeholders = [match.group(0) for pattern in _PROSE_PLACEHOLDERS if (match := pattern.search(prose))]
    # Masking blanks HTML comments along with tags, so a comment abridging the
    # page is read from the raw text; only comments carrying an abridgement
    # word count, so an ordinary comment is not a placeholder.
    placeholders += [c.group(0) for c in _COMMENT.finditer(output) if _ABRIDGED.search(c["body"])]
    messages = [f"placeholder text {found!r} — translate the whole block, never abridge" for found in placeholders]
    if script == "latin":
        return messages
    # A non-Latin-script language: a long unbroken run of Latin words that are
    # not glossary keep-terms is prose the model left in English.
    for term in glossary.keep_in_source_language:
        prose = _term_pattern(term).sub(" ", prose)
    if run := _LATIN_RUN.search(prose):
        messages.append(f"untranslated English left in the text: {' '.join(run.group(0).split()[:6])!r} ...")
    return messages
