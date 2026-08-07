"""Machine-translate the documentation and stage the translated sites for the build.

English under `docs/` is the source of truth. Each language listed in
`i18n/languages.yml` gets generated pages under `i18n/<code>/pages/`, driven
by that language's human-written `instructions.md` and `glossary.json` (see
`i18n/README.md`). Corrections go into those inputs, never into the generated
pages.

Usage:
    python scripts/docs/translations.py languages           # enabled codes, one per line
    python scripts/docs/translations.py status [--lang ja]  # what is missing/outdated
    python scripts/docs/translations.py translate --lang ja [--pages a.md ...] [--fresh] [--dry-run] [--no-verify]
    python scripts/docs/translations.py stage --lang ja      # assemble the docs tree the language site builds from

`translate` calls the model (set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`);
every other command is offline.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
import yaml
from llms_txt import page_url

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS = ROOT / "docs"
I18N = ROOT / "i18n"
ATTEMPTS = 3


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Registry (i18n/languages.yml) and a language's prompt inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    theme_language: str
    hreflang: str


@dataclass(frozen=True)
class Registry:
    languages: list[Language]
    exclude_pages: list[str]
    models: dict[str, str]  # {"translate": ..., "verify": ...}
    banners: dict[str, str]  # kind -> English notice with {english_url}/{translations_url} placeholders

    def language(self, code: str) -> Language:
        for language in self.languages:
            if language.code == code:
                return language
        raise SystemExit(f"i18n: unknown language code {code!r} (see i18n/languages.yml)")


def load_registry() -> Registry:
    """The language registry, English banner sources and model ids from `i18n/languages.yml`."""
    data = yaml.safe_load((I18N / "languages.yml").read_text(encoding="utf-8"))
    languages = [
        Language(
            item["code"], item["name"], item.get("theme_language", item["code"]), item.get("hreflang", item["code"])
        )
        for item in data["languages"]
    ]
    return Registry(languages, data.get("exclude_pages", []), data["models"], data["banners"])


@dataclass(frozen=True)
class Inputs:
    """The human-written prompt inputs of one language; `hash` fingerprints all of them."""

    language: Language
    general_prompt: str
    instructions: str
    glossary: dict[str, Any]
    hash: str


def load_inputs(language: Language) -> Inputs:
    general = (I18N / "general-prompt.md").read_text(encoding="utf-8")
    instructions = (I18N / language.code / "instructions.md").read_text(encoding="utf-8")
    glossary = (I18N / language.code / "glossary.json").read_text(encoding="utf-8")
    return Inputs(language, general, instructions, json.loads(glossary), sha256(general + instructions + glossary))


# ---------------------------------------------------------------------------
# Pages and sidebar labels, both read from mkdocs.yml
# ---------------------------------------------------------------------------


def mkdocs_config() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))


def _nav_entries(nav: list[Any]) -> Iterable[tuple[str | None, str]]:
    """Every `(label, page)` of the nav in order; a bare page has no label, a section title has no page."""
    for entry in nav:
        if isinstance(entry, str):
            yield None, entry
            continue
        label, value = next(iter(entry.items()))
        if isinstance(value, list):
            yield label, ""
            yield from _nav_entries(value)
        else:
            yield label, value


def translatable_pages(nav: list[Any], exclude: list[str]) -> list[str]:
    """The prose pages each language should carry, in nav order (the API reference stays English)."""
    excluded = tuple(pattern.removesuffix("**") for pattern in ["api/", *exclude])
    return [page for _, page in _nav_entries(nav) if page.endswith(".md") and not page.startswith(excluded)]


def nav_labels(nav: list[Any]) -> list[str]:
    """The sidebar labels (section titles and `Label: page.md` entries) in nav order, deduplicated."""
    return list(dict.fromkeys(label for label, _ in _nav_entries(nav) if label))


def read_page(root: Path, page: str) -> str:
    return (root / page).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markdown structure: fences, headings and their anchors, links, ##-sections
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^[ \t]*(?P<run>`{3,}|~{3,})(?P<info>[^\n]*)$")
_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t]*$")
_ANCHOR = re.compile(r"[ \t]+\{[ \t]*#(?P<id>[^}\s]+)[^}]*\}[ \t]*$")
_CODE_SPAN = re.compile(r"(?<!\\)(`+)(?P<code>.+?)(?<!`)\1(?!`)")
_LINK = re.compile(r"(?P<image>!?)\[(?P<label>[^\]]*)\]\((?P<target>[^)\s]*)(?P<title>[^)]*)\)")
_HTML_TARGET = re.compile(r"""<(?P<tag>a|img)\b[^>]*?\b(?:href|src)=(?P<q>["'])(?P<target>.*?)(?P=q)""", re.IGNORECASE)
_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[!-~]+")
_TAG = re.compile(r"</?[A-Za-z][^>\n]*>|<!--.*?-->", re.DOTALL)
_MARKER = re.compile(r"^[ \t]*(?P<marker>!!!|\?\?\?\+?|===)[ \t]+(?P<kind>[\w-]+|\")")
_EXTERNAL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
_PLACEHOLDER = re.compile(
    r"\[\s*(?:translation|rest of|remaining)[^\]]*\]|\((?:content )?omitted[^)]*\)|\[\s*\.\.\.\s*\]", re.IGNORECASE
)


@dataclass(frozen=True)
class Heading:
    line: int
    level: int
    text: str
    anchor: str | None  # the explicit {#id}, if written


def fences(lines: list[str]) -> list[tuple[int, int | None]]:
    """`(opener, closer)` line indices of each fenced code block; `closer` is None if the fence never closes."""
    found: list[tuple[int, int | None]] = []
    opener: re.Match[str] | None = None
    start = 0
    for index, line in enumerate(lines):
        match = _FENCE.match(line)
        if opener is None:
            if match:
                opener, start = match, index
        elif match and match["run"][0] == opener["run"][0] and len(match["run"]) >= len(opener["run"]):
            found.append((start, index))
            opener = None
    if opener is not None:
        found.append((start, None))
    return found


def _code_lines(lines: list[str]) -> set[int]:
    """Indices of every line that belongs to a fenced code block (markers included)."""
    inside: set[int] = set()
    for start, end in fences(lines):
        inside.update(range(start, len(lines) if end is None else end + 1))
    return inside


def headings(text: str) -> list[Heading]:
    """The ATX headings outside code fences, with an explicit trailing `{#id}` split off the text."""
    lines = text.split("\n")
    code = _code_lines(lines)
    found: list[Heading] = []
    for index, line in enumerate(lines):
        if index in code or not (match := _HEADING.match(line)):
            continue
        heading, anchor = match["text"], None
        if attrs := _ANCHOR.search(heading):
            heading, anchor = heading[: attrs.start()], attrs["id"]
        found.append(Heading(index, len(match["hashes"]), heading, anchor))
    return found


def slugify(text: str) -> str:
    """A heading's rendered id: python-markdown's default `toc` slugify applied to the heading's plain text.

    Code spans and backslash escapes are literal text (stashed first so their
    underscores survive), links keep only their label, underscore emphasis at
    word boundaries and inline tags contribute nothing.
    """
    literals: list[str] = []

    def stash(value: str) -> str:
        literals.append(value)
        return f"\x02{len(literals) - 1}\x03"

    plain = _CODE_SPAN.sub(lambda match: stash(match["code"].strip()), text)
    plain = re.sub(r"\\([\\`*_{}\[\]()>#+.!-])", lambda match: stash(match.group(1)), plain)
    plain = _LINK.sub(lambda match: match["label"], plain)
    plain = re.sub(r"(?<!\w)(_{1,2})(.+?)\1(?!\w)", r"\2", plain)
    plain = re.sub(r"</?[A-Za-z][^<>]*>", "", plain)
    plain = html.unescape(re.sub(r"\x02(\d+)\x03", lambda match: literals[int(match.group(1))], plain))
    ascii = unicodedata.normalize("NFKD", plain).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", ascii).strip().lower())


def heading_ids(text: str) -> list[str]:
    """The rendered id of each heading of a page, in order: its explicit `{#id}`, or its deduplicated slug."""
    found = headings(text)
    used = {heading.anchor for heading in found if heading.anchor}
    ids: list[str] = []
    for heading in found:
        slug = heading.anchor or slugify(heading.text)
        base, number = slug, 0
        while heading.anchor is None and (not slug or slug in used):
            number += 1
            slug = f"{base}_{number}"
        used.add(slug)
        ids.append(slug)
    return ids


def with_anchors(text: str) -> str:
    """The page with every heading's rendered id pinned as an explicit `{#id}` anchor."""
    lines = text.split("\n")
    for heading, anchor in zip(headings(text), heading_ids(text), strict=True):
        lines[heading.line] = f"{'#' * heading.level} {heading.text} {{#{anchor}}}"
    return "\n".join(lines)


def _prose_words(heading: Heading, keep: set[str]) -> list[str]:
    """The heading's translatable English words: not inside a code span and not a keep-in-English term."""
    return [word for word in re.findall(r"[A-Za-z]+", _CODE_SPAN.sub("", heading.text)) if word not in keep]


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """Overwrite each span with same-length blanks (newlines kept), so positions and line numbers survive."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def without_fences(text: str) -> str:
    """The text with every fenced code block blanked (lines and lengths kept, so positions survive)."""
    lines = text.split("\n")
    code = _code_lines(lines)
    return "\n".join(" " * len(line) if index in code else line for index, line in enumerate(lines))


def code_spans(text: str) -> list[str]:
    """The inline code spans of a page's prose, by content (fenced code excluded)."""
    return [match["code"].strip() for match in _CODE_SPAN.finditer(without_fences(text))]


def mask(text: str, *, prose_only: bool = True) -> str:
    """Blank code fences and inline code spans; with `prose_only`, also bare URLs, HTML tags and link targets."""
    masked = without_fences(text)
    masked = _blank(masked, [match.span() for match in _CODE_SPAN.finditer(masked)])
    if prose_only:
        for pattern in (_URL, _TAG):
            masked = _blank(masked, [match.span() for match in pattern.finditer(masked)])
        masked = _blank(masked, [match.span("target") for match in _LINK.finditer(masked)])
    return masked


def links(text: str) -> list[str]:
    """Every markdown and HTML link/image target written in the page's prose."""
    prose = mask(text, prose_only=False)
    return [match["target"] for pattern in (_LINK, _HTML_TARGET) for match in pattern.finditer(prose)]


def rewrite_links(text: str, transform: Callable[[str], str]) -> str:
    """Replace each prose link/image target with `transform(target)`; code is not touched."""
    prose = mask(text, prose_only=False)
    spans = sorted(m.span("target") for pattern in (_LINK, _HTML_TARGET) for m in pattern.finditer(prose))
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts += [text[cursor:start], transform(text[start:end])]
        cursor = end
    return "".join([*parts, text[cursor:]])


def markers(text: str) -> list[str]:
    """The admonition (`!!!`/`???`), collapsible and content-tab (`===`) markers of a page, in order."""
    return [
        f"{m['marker']} {m['kind']}" for line in mask(text, prose_only=False).split("\n") if (m := _MARKER.match(line))
    ]


def blocks(text: str) -> list[str]:
    """The page as sections: the text before the first `##` heading, then one block per `##` heading.

    `"\\n".join(blocks(text)) == text`, so one section can be swapped without disturbing its neighbours.
    """
    lines = text.split("\n")
    starts = [0, *(heading.line for heading in headings(text) if heading.level == 2 and heading.line)]
    return ["\n".join(lines[start:end]) for start, end in zip(starts, [*starts[1:], None])]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def glossary_prompt(glossary: dict[str, Any]) -> str:
    """The glossary as the prompt section the model sees."""
    lines = ["## Glossary", "", "These terms always stay in English, spelled exactly like this:", ""]
    lines += [f"- {term}" for term in glossary["keep_in_source_language"]]
    lines += ["", "Use these renderings; the notes are binding:", ""]
    for term in glossary["terms"]:
        entry = f"- {term['source']} → {term['target']}"
        if term.get("avoid"):
            entry += f" (never: {', '.join(term['avoid'])})"
        if term.get("note"):
            entry += f". {term['note']}"
        lines.append(entry)
    return "\n".join(lines)


def system_prompt(inputs: Inputs) -> str:
    """The cacheable prompt prefix: the shared rules, then this language's style guide and glossary."""
    header = f"# Target language: {inputs.language.name} (`{inputs.language.code}`)"
    parts = (inputs.general_prompt, header, inputs.instructions, glossary_prompt(inputs.glossary))
    return "\n\n".join(part.strip() for part in parts)


def translate_request(source: str) -> str:
    return (
        "Translate the following Markdown page. Return only the translated page."
        f"\n\n<english-page>\n{source}\n</english-page>"
    )


def update_request(source: str, changed: list[str], previous: str) -> str:
    listed = "\n".join(f"- {label}" for label in changed)
    return (
        "This page was translated before and only part of the English changed. Retranslate it: translate the"
        " changed sections listed here afresh from the current English (their previous translation is stale, so do"
        " not reuse its wording for them), and reproduce the previous translation verbatim everywhere else,"
        " keeping the changed sections consistent in terminology and tone with their surroundings. A section is"
        f" the introduction before the first `##` heading, or one `##` heading with everything under it.\n\n"
        f"Changed sections:\n\n{listed}\n\nCurrent English page:\n\n<english-page>\n{source}\n</english-page>\n\n"
        f"Previous translation of the page:\n\n<previous-translation>\n{previous}\n</previous-translation>\n\n"
        "Return only the full translated page."
    )


def repair_request(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return (
        "Your reply broke the following rules. Fix each problem and return the full corrected reply, changing"
        f" nothing else:\n\n{listed}"
    )


VERIFY_SYSTEM = """\
You are an adversarial bilingual reviewer of technical documentation. You are shown an English page and its \
machine translation. Your only job is to find places where the translation would make a developer believe or \
do something different from the English. Ignore style, tone, register and word order; a fluent paraphrase is not \
a problem.

Hunt specifically for:
- a dropped or added negation ("must not" becoming "must", "never" disappearing)
- an inverted or altered condition ("unless", "only if", "as long as")
- swapped actors (client vs server, user vs model, caller vs handler)
- reversed cause and effect
- changed obligation strength (must / should / may / cannot)
- a wrong-sense word choice that changes what the reader would do
- an added or removed security-relevant statement

Severity: "blocker" when a reader following the translation would do the wrong thing or believe something \
false; "drift" for a real but harmless meaning shift.

Rules for reporting:
- Quote the exact English words and the exact translated words the problem is in. Both quotes must be copied \
literally from the texts you were given; a finding whose quotes are not literal substrings is discarded.
- Do not invent problems. Most pages are fine, and an empty list is the correct answer for them. Never report \
style preferences, terminology you would render differently, or word order.
- Answer with a JSON array only, no prose. Each element is an object with the keys "severity", "source_quote", \
"target_quote", "explanation" (one sentence).

Calibration:
- English "you should not cache this token" translated with the negation dropped, so it now tells the reader \
to cache it: report {"severity": "blocker", ...}.
- English "the server may retry" rendered as the equivalent of "the server retries" (a possibility turned into a \
certainty): report {"severity": "drift", ...}.
- English "Register the tool before starting the server" rendered as an idiomatic sentence with the clauses \
reordered but the same instruction: report nothing for it.\
"""


def parse_review(reply: str, source: str, output: str) -> list[dict[str, str]] | None:
    """The reviewer's findings, keeping only those whose quotes are literal (whitespace-collapsed) substrings.

    None means the reply was not the JSON array asked for.
    """
    try:
        parsed = json.loads(reply[reply.index("[") : reply.rindex("]") + 1])
    except ValueError:
        return None

    def squash(text: object) -> str:
        return " ".join(str(text).split())

    source_flat, output_flat = squash(source), squash(output)
    return [
        {key: str(finding.get(key, "")) for key in ("severity", "source_quote", "target_quote", "explanation")}
        for finding in parsed
        if isinstance(finding, dict)
        and (english := squash(finding.get("source_quote") or "\0")) in source_flat
        and (rendered := squash(finding.get("target_quote") or "\0")) in output_flat
        and english
        and rendered
    ]


# ---------------------------------------------------------------------------
# The translation pipeline: model call, mechanical repair, carry-forward, gate
# ---------------------------------------------------------------------------


class Model:
    """The Claude API client behind `translate`; every call carries the system prompt as a cacheable prefix."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def complete(self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        prefix: list[Any] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        with self._client.messages.stream(model=model, system=prefix, messages=messages, max_tokens=max_tokens) as s:
            message = s.get_final_message()
        if message.stop_reason == "max_tokens":
            raise RuntimeError(f"{model} ran out of output tokens")
        return "".join(block.text for block in message.content if block.type == "text")


def repair(source: str, output: str) -> str:
    """Re-impose what the model must never change: the wrapper stripped, heading anchors, code fence bodies."""
    lines = output.strip("\n").split("\n")
    if not source.startswith(("```", "~~~")) and len(lines) > 1 and _FENCE.match(lines[0]) and _FENCE.match(lines[-1]):
        lines = lines[1:-1]
    expected, found = headings(source), headings("\n".join(lines))
    if len(expected) == len(found):
        for want, got in zip(expected, found):
            lines[got.line] = f"{'#' * got.level} {got.text} {{#{want.anchor}}}"
    source_lines = source.split("\n")
    source_fences, output_fences = fences(source_lines), fences(lines)
    if len(source_fences) == len(output_fences):
        # Splice from the last fence up so an edit never shifts the fences still to do.
        for (start, end), (out_start, out_end) in reversed(list(zip(source_fences, output_fences))):
            if end is not None and out_end is not None:
                lines[out_start + 1 : out_end] = source_lines[start + 1 : end]
    text = "\n".join(lines)
    return text + "\n" if source.endswith("\n") and not text.endswith("\n") else text


def block_hashes(source: str) -> list[str]:
    """The content hash of each `##` section of the (anchor-pinned) English page, in order."""
    return [sha256(block) for block in blocks(source)]


def carry_forward(source: str, output: str, old_hashes: list[str], old_output: str) -> str:
    """Overwrite every unchanged section of `output` with its prior translation, byte-for-byte.

    `old_hashes` are the recorded hashes of the English sections `old_output` was
    translated from, so a section whose English is unchanged maps to the exact
    bytes it had before.
    """
    prior = dict(zip(old_hashes, blocks(old_output), strict=True))
    translated = blocks(output)
    if len(translated) != len(hashes := block_hashes(source)):
        return output
    return "\n".join(prior.get(hash, done) for hash, done in zip(hashes, translated))


def structural_findings(source: str, output: str, glossary: dict[str, Any]) -> list[str]:
    """The structural problems of a translation, worded as repair instructions (empty means it passes)."""
    problems: list[str] = []
    if (want := len(blocks(source))) != len(blocks(output)):
        problems.append(f"the page must keep the same {want} `##` sections as the English, in the same order")
    if [h.level for h in headings(source)] != [h.level for h in headings(output)]:
        problems.append("keep every heading, at the same level and in the same order as the English")
    source_fences, output_fences = fences(source.split("\n")), fences(output.split("\n"))
    if len(source_fences) != len(output_fences) or any(end is None for _, end in output_fences):
        problems.append(f"keep the same {len(source_fences)} closed code fences as the English, copied exactly")
    if markers(source) != markers(output):
        problems.append("keep the same admonition/collapsible/tab markers (`!!!`, `???`, `===` and their type)")
    expected, found = Counter(links(source)), Counter(links(output))
    source_spans, output_spans = set(code_spans(source)), set(code_spans(output))  # counts free to vary
    for wording, difference in (
        ("missing link targets", sorted((expected - found).elements())),
        ("unexpected link targets", sorted((found - expected).elements())),
        ("missing inline code spans", sorted(source_spans - output_spans)),
        ("unexpected inline code spans", sorted(output_spans - source_spans)),
    ):
        if difference:
            problems.append(f"{wording} {difference} — copy each one exactly from the English")
    keep = set(glossary["keep_in_source_language"])
    prose_headings = [(want, got) for want, got in zip(headings(source), headings(output)) if _prose_words(want, keep)]
    if len(kept := [want.text for want, got in prose_headings if want.text == got.text]) * 2 > len(prose_headings) > 2:
        problems.append(f"these headings are still English — translate their text, keeping the anchors: {kept}")
    prose, source_prose = mask(output), mask(source)
    problems.extend(
        f"placeholder text {placeholder!r} — translate the whole page, never abridge it"
        for placeholder in dict.fromkeys(_PLACEHOLDER.findall(prose))
    )
    problems.extend(
        f"banned rendering {banned!r} of {term['source']!r} appears; use the glossary target"
        for term in glossary["terms"]
        if term.get("enforce")
        for banned in term.get("avoid", [])
        if banned in prose
    )
    for term in glossary["keep_in_source_language"]:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        if re.search(pattern, source_prose) and not re.search(pattern, prose):
            problems.append(f"{term!r} must appear verbatim, spelled exactly as in the English")
    return problems


def review(source: str, output: str, model: Model, verify_model: str) -> list[dict[str, str]]:
    """The second model's meaning-change findings for a translated page.

    Raises:
        RuntimeError: The reviewer's reply was not a JSON array twice in a row.
    """
    request = f"<english>\n{source}\n</english>\n\n<translation>\n{output}\n</translation>"
    for _ in range(2):
        reply = model.complete(verify_model, VERIFY_SYSTEM, [{"role": "user", "content": request}], 16_000)
        if (findings := parse_review(reply, source, output)) is not None:
            return findings
    raise RuntimeError("the reviewer gave an unparseable reply")


def translate_page(
    source: str,
    inputs: Inputs,
    model: Model,
    models: dict[str, str],
    *,
    previous: str | None = None,
    old_hashes: list[str] | None = None,
    verify: bool = True,
) -> tuple[str | None, list[str]]:
    """Translate one page (`source` is the English with anchors pinned) and gate it.

    With the page's previous translation and the recorded hashes of the English
    sections it was made from (`old_hashes`), only the changed `##` sections are
    re-translated and the rest is carried forward byte-for-byte. Returns
    `(text, [])`, or `(None, reasons)` when the page failed its structural or
    meaning gate.
    """
    # The prior translation and the section hashes it was made from, when both are usable.
    prior = (previous, old_hashes) if previous and old_hashes and len(old_hashes) == len(blocks(previous)) else None
    if prior:
        if (hashes := block_hashes(source)) == prior[1]:  # the same sections as before: nothing to do
            return prior[0], []
        old = set(prior[1])
        changed = [
            block.split("\n", 1)[0] if index else "the introduction (before the first `##` heading)"
            for index, (block, hash) in enumerate(zip(blocks(source), hashes))
            if hash not in old
        ] or [
            "(no section is new — sections were removed or reordered, so give the page exactly the sections"
            " of the current English)"
        ]
        request = update_request(source, changed, prior[0])
    else:
        request = translate_request(source)
    messages: list[dict[str, str]] = [{"role": "user", "content": request}]
    system = system_prompt(inputs)

    def attempt(carry: bool = True) -> str:
        """One model call, mechanically repaired; unchanged sections carried over from the prior translation."""
        reply = repair(source, model.complete(models["translate"], system, messages, min(64_000, 16_000 + len(source))))
        return carry_forward(source, reply, prior[1], prior[0]) if carry and prior else reply

    output, problems = "", ["not translated"]
    for _ in range(ATTEMPTS):
        output = attempt()
        if not (problems := structural_findings(source, output, inputs.glossary)):
            break
        messages += [{"role": "assistant", "content": output}, {"role": "user", "content": repair_request(problems)}]
    if problems:
        return None, problems
    if not verify:
        return output, []

    found = review(source, output, model, models["verify"])
    if blockers := [f for f in found if f["severity"] == "blocker"]:
        # One correction round (free to reword even the carried-over sections it names);
        # a blocker that survives it fails the page.
        fixes = [
            f'English "{f["source_quote"]}" was rendered as "{f["target_quote"]}": {f["explanation"]}' for f in blockers
        ]
        correction = (
            "A bilingual reviewer found places where your translation changed the meaning of the English."
            " Correct each one and return the full corrected page, changing nothing else:\n\n"
            + "\n".join(f"- {fix}" for fix in fixes)
        )
        messages += [{"role": "assistant", "content": output}, {"role": "user", "content": correction}]
        output = attempt(carry=False)
        if problems := structural_findings(source, output, inputs.glossary):
            return None, problems
        found = review(source, output, model, models["verify"])
        if surviving := [f for f in found if f["severity"] == "blocker"]:
            return None, [
                f'meaning: "{f["source_quote"]}" -> "{f["target_quote"]}": {f["explanation"]}' for f in surviving
            ]
    for drift in found:
        print(f'  note: "{drift["source_quote"]}" -> "{drift["target_quote"]}": {drift["explanation"]}')
    return output, []


# ---------------------------------------------------------------------------
# UI strings: sidebar labels and banners, translated in one JSON-map call
# ---------------------------------------------------------------------------


def ui_strings(registry: Registry) -> dict[str, str]:
    """The English UI strings of a language site: every sidebar label, plus each banner (`@banner:<kind>`)."""
    labels = {label: label for label in nav_labels(mkdocs_config()["nav"])}
    return {**labels, **{f"@banner:{kind}": text for kind, text in registry.banners.items()}}


def ui_findings(strings: dict[str, str], translated: dict[str, str]) -> list[str]:
    """Problems of a translated UI-string map: it must key every string, non-empty, banner placeholders intact."""
    if missing := [key for key in strings if not str(translated.get(key, "")).strip()]:
        return [f"reply must be one JSON object with a non-empty string for each of these keys: {missing}"]
    problems: list[str] = []
    for key, source in strings.items():
        # A banner is later filled with str.format, so the fields must match and the braces must be balanced.
        want, value = set(re.findall(r"\{[^{}]*\}", source)), str(translated[key])
        try:
            value.format(**{field.strip("{}"): "" for field in want})
        except (ValueError, KeyError, IndexError):
            good = False
        else:
            good = want == set(re.findall(r"\{[^{}]*\}", value))
        if not good:
            problems.append(f"{key}: keep exactly the placeholders {sorted(want)} and no other braces")
    return problems


def kept_ui(strings: dict[str, str], state: dict[str, Any], inputs: Inputs) -> dict[str, str]:
    """The prior renderings still valid for these UI strings: same prompt inputs and unchanged English source."""
    ui = state["ui"]
    if ui.get("inputs_hash") != inputs.hash:
        return {}
    old_strings, old_source = ui.get("strings", {}), ui.get("source", {})
    return {key: old_strings[key] for key in strings if key in old_strings and old_source.get(key) == strings[key]}


def translate_ui(
    strings: dict[str, str], inputs: Inputs, model: Model, models: dict[str, str], keep: dict[str, str]
) -> dict[str, str] | None:
    """Translate the UI strings; the still-valid prior renderings (`keep`) are reused verbatim."""
    request = (
        "Translate the values of this JSON object. Each `@banner:` value is a short Markdown notice shown on the"
        " translated documentation pages: keep its admonition line, links and `{...}` placeholders exactly as"
        " written and translate only the human text. Every other value is one sidebar navigation label: a compact"
        " noun phrase, never a sentence. Apply the glossary and the language instructions.\n\n"
        + json.dumps(strings, ensure_ascii=False, indent=2)
        + (
            "\n\nThese entries were translated before; reuse each rendering verbatim and keep the new ones consistent"
            " with them:\n\n" + json.dumps(keep, ensure_ascii=False, indent=2)
            if keep
            else ""
        )
        + "\n\nReturn only the same JSON object with every value translated — no other text."
    )
    messages: list[dict[str, str]] = [{"role": "user", "content": request}]
    for _ in range(ATTEMPTS):
        reply = model.complete(models["translate"], system_prompt(inputs), messages, 16_000)
        try:
            translated = {**json.loads(reply[reply.index("{") : reply.rindex("}") + 1]), **keep}
        except ValueError:
            translated = {}
        problems = ui_findings(strings, translated)
        if not problems:
            return {key: str(translated[key]) for key in strings}
        messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": repair_request(problems)}]
    return None


# ---------------------------------------------------------------------------
# State (i18n/<code>/state.json): what each generated file was made from
# ---------------------------------------------------------------------------


def load_state(code: str) -> dict[str, Any]:
    path = I18N / code / "state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"pages": {}, "ui": {}}


def save_state(code: str, state: dict[str, Any]) -> None:
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (I18N / code / "state.json").write_text(text, encoding="utf-8", newline="")


def page_status(page: str, code: str, state: dict[str, Any], inputs: Inputs) -> str:
    """`missing` (no translation), `outdated` (the English or the prompt inputs moved on) or `current`."""
    record = state["pages"].get(page)
    if record is None or not (I18N / code / "pages" / page).is_file():
        return "missing"
    fresh = record["source_hash"] == sha256(read_page(DOCS, page)) and record["inputs_hash"] == inputs.hash
    return "current" if fresh else "outdated"


def ui_status(state: dict[str, Any], strings: dict[str, str], inputs: Inputs) -> str:
    if not (ui := state["ui"]):
        return "missing"
    fresh = (
        ui.get("source_hash") == sha256(json.dumps(strings, sort_keys=True)) and ui.get("inputs_hash") == inputs.hash
    )
    return "current" if fresh else "outdated"


# ---------------------------------------------------------------------------
# Stage: the docs tree a language site is built from
# ---------------------------------------------------------------------------


def staged_docs(code: str) -> Path:
    return ROOT / ".build" / "i18n" / code / "docs"


def stage(language: Language, site_url: str, registry: Registry) -> Path:
    """Overlay the translations on the English tree, inject banners, point API links at the English reference.

    An outdated translation is served only when it cannot break the strict
    build: every link it makes resolves against the current English tree and
    its headings carry every anchor the current English page renders (so links
    into it resolve too); otherwise the English page is served with the
    not-translated notice until the next translate run refreshes it.
    """
    target = staged_docs(language.code)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(DOCS, target, ignore=shutil.ignore_patterns("api", ".*"))
    state, inputs = load_state(language.code), load_inputs(language)
    strings = state["ui"].get("strings", {})
    banners = {
        **registry.banners,
        **{k.removeprefix("@banner:"): v for k, v in strings.items() if k.startswith("@banner:")},
    }
    nav = mkdocs_config()["nav"]
    prose = translatable_pages(nav, [])
    universe = {page: heading_ids(read_page(DOCS, page)) for page in prose}
    translatable = set(translatable_pages(nav, registry.exclude_pages))
    for page in prose:
        english = read_page(DOCS, page)
        status = page_status(page, language.code, state, inputs) if page in translatable else "excluded"
        body, kinds = english, ["untranslated"]
        if status in ("current", "outdated"):
            translated = read_page(I18N / language.code / "pages", page)
            if status == "current" or servable(translated, page, universe):
                body, kinds = translated, ["disclosure"] + (["outdated"] if status == "outdated" else [])
            else:
                print(
                    f"note: {language.code}: serving English for {page} until the next translate run"
                    " (its translation's links or anchors no longer match the English tree)",
                    file=sys.stderr,
                )
        body = rewrite_links(body, lambda target: api_reference_url(page, target, site_url))
        variables = {
            "english_url": f"{site_url}/{page_url(page)}",
            "translations_url": relative(page, "translations.md"),
        }
        banner = "\n\n".join(banners[kind].strip().format(**variables) for kind in kinds)
        (target / page).write_text(inject_banner(body, banner), encoding="utf-8", newline="")
    return target


def resolve_link(page: str, target: str) -> str | None:
    """The docs-relative path a page's relative link points at, or None for external/absolute/escaping targets."""
    if not target or _EXTERNAL.match(target) or target.startswith(("/", "#")):
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(page), target))
    return None if resolved.startswith("..") else resolved


def api_reference_url(page: str, target: str, site_url: str) -> str:
    """A relative link into the (English-only) API reference made absolute; any other target unchanged."""
    path, _, fragment = target.partition("#")
    resolved = resolve_link(page, path)
    if resolved is None or not resolved.startswith("api/"):
        return target
    return f"{site_url}/{page_url(resolved)}" + (f"#{fragment}" if fragment else "")


def servable(translated: str, page: str, universe: dict[str, list[str]]) -> bool:
    """Whether an outdated translation still fits the current English tree (its own anchors and every link)."""
    own = set(heading_ids(translated))
    if not set(universe.get(page, [])) <= own:
        return False
    for target in links(translated):
        path, _, fragment = target.partition("#")
        resolved = page if target.startswith("#") else resolve_link(page, path)
        if resolved is None or resolved.startswith("api/"):
            continue
        anchors = own if resolved == page else universe.get(resolved, [])
        if not (DOCS / resolved).exists() or (fragment and fragment not in anchors):
            return False
    return True


def relative(page: str, other: str) -> str:
    """The relative link from `page` to `other` (both docs-relative)."""
    return "../" * len(Path(page).parent.parts) + other


def inject_banner(text: str, banner: str) -> str:
    """Insert the banner right after the page's `#` title line (or at the top if the page has none)."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join([*lines[: index + 1], "", banner, *lines[index + 1 :]])
    return "\n".join([banner, "", *lines])


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def command_status(registry: Registry, code: str | None) -> int:
    pages = translatable_pages(mkdocs_config()["nav"], registry.exclude_pages)
    for language in [registry.language(code)] if code else registry.languages:
        state, inputs = load_state(language.code), load_inputs(language)
        statuses = {page: page_status(page, language.code, state, inputs) for page in pages}
        counts = Counter(statuses.values())
        print(
            f"{language.code} ({language.name}): {counts['missing']} missing, {counts['outdated']} outdated,"
            f" {counts['current']} current; UI strings {ui_status(state, ui_strings(registry), inputs)}"
        )
        for page, status in statuses.items():
            if status != "current":
                print(f"  {status:<9} {page}")
        for stray in sorted(set(state["pages"]) - set(pages)):
            print(f"  removable {stray} (English page gone or excluded; the next translate run deletes it)")
    return 0


def command_translate(registry: Registry, args: argparse.Namespace) -> int:
    language = registry.language(args.lang)
    state, inputs = load_state(language.code), load_inputs(language)
    all_pages = translatable_pages(mkdocs_config()["nav"], registry.exclude_pages)
    if unknown := [page for page in args.pages if page not in all_pages]:
        raise SystemExit(f"i18n: not translatable pages (docs-relative nav paths, e.g. servers/tools.md): {unknown}")
    if args.pages:
        pages = args.pages
    elif args.fresh:
        pages = all_pages
    else:
        pages = [page for page in all_pages if page_status(page, language.code, state, inputs) != "current"]
    strays = sorted(set(state["pages"]) - set(all_pages))  # their English pages left the nav (or were excluded)
    strings = ui_strings(registry)
    refresh_ui = ui_status(state, strings, inputs) != "current"
    if args.dry_run:
        deleting = f" and delete {len(strays)} stray translation(s)" if strays else ""
        print(
            f"{language.code}: would translate {len(pages)} page(s)"
            f"{' and the UI strings' if refresh_ui else ''}{deleting}"
        )
        print("\n".join(f"  {page}" for page in pages))
        return 0
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit("i18n: set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) to translate")
    for stray in strays:
        (I18N / language.code / "pages" / stray).unlink(missing_ok=True)
        del state["pages"][stray]
        print(f"deleted: {stray}")
    if strays:
        save_state(language.code, state)

    model, models, failed = Model(), registry.models, False
    stamp = {
        "inputs_hash": inputs.hash,
        "model": models["translate"],
        "translated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        if refresh_ui:
            try:
                translated = translate_ui(strings, inputs, model, models, kept_ui(strings, state, inputs))
            except RuntimeError as exc:  # a truncated model reply
                translated = None
                print(f"  {exc}", file=sys.stderr)
            if translated is None:
                failed = True
                print("error: UI strings failed", file=sys.stderr)
            else:
                state["ui"] = {
                    "strings": translated,
                    "source": strings,
                    "source_hash": sha256(json.dumps(strings, sort_keys=True)),
                    **stamp,
                }
                save_state(language.code, state)
                print(f"translated: UI strings ({len(translated)} entries)")
        for page in pages:
            record = state["pages"].get(page) if not args.fresh else None
            target = I18N / language.code / "pages" / page
            english = read_page(DOCS, page)
            source = with_anchors(english)
            previous = target.read_text(encoding="utf-8") if record and target.is_file() else None
            old_hashes = record.get("block_hashes") if record and record.get("inputs_hash") == inputs.hash else None
            try:
                text, problems = translate_page(
                    source, inputs, model, models, previous=previous, old_hashes=old_hashes, verify=not args.no_verify
                )
            except RuntimeError as exc:  # a truncated or unusable model reply fails this page, not the run
                text, problems = None, [str(exc)]
            if text is None:
                failed = True
                print(f"error: {page} failed:", file=sys.stderr)
                print("\n".join(f"  {problem}" for problem in problems), file=sys.stderr)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="")
            state["pages"][page] = {"source_hash": sha256(english), "block_hashes": block_hashes(source), **stamp}
            save_state(language.code, state)
            print(f"{'unchanged' if text == previous else 'translated'}: {page}")
    except anthropic.APIError as exc:  # what is done is saved; a rerun resumes where this stopped
        raise SystemExit(f"i18n: Claude API error: {exc}") from exc
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("languages", help="print the enabled language codes")
    status = commands.add_parser("status", help="list missing, outdated and current pages per language")
    status.add_argument("--lang", metavar="CODE")
    translate = commands.add_parser("translate", help="translate pages and the UI strings (calls the model)")
    translate.add_argument("--lang", metavar="CODE", required=True)
    translate.add_argument("--pages", nargs="+", metavar="PAGE", default=[], help="only these pages")
    translate.add_argument("--fresh", action="store_true", help="re-translate from scratch (every page if none given)")
    translate.add_argument("--dry-run", action="store_true", help="list what would be translated and exit")
    translate.add_argument("--no-verify", action="store_true", help="skip the second-model meaning review")
    staged = commands.add_parser("stage", help="assemble a language's docs tree for the build")
    staged.add_argument("--lang", metavar="CODE", required=True)
    staged.add_argument("--site-url", metavar="URL", help="URL the site is served from (default: mkdocs.yml)")
    args = parser.parse_args()

    registry = load_registry()
    if args.command == "languages":
        print("\n".join(language.code for language in registry.languages))
    elif args.command == "status":
        return command_status(registry, args.lang)
    elif args.command == "translate":
        return command_translate(registry, args)
    else:
        site_url = (args.site_url or mkdocs_config()["site_url"]).rstrip("/")
        print(f"staged {stage(registry.language(args.lang), site_url, registry).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
