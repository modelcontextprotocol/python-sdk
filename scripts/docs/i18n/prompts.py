"""Prompt assembly for the translation and semantic-review calls.

The system prompt is the static, cacheable prefix — general rules, then the
language's instructions, then its glossary — shared by every page of a
language and by its navigation labels. The user message carries the page
(and, on an update, the previous translation and the list of changed
sections), or the numbered list of sidebar labels. The reviewer prompt drives
the second, stronger model to hunt meaning-changing errors between one
English block and its translation, and its parser discards anything it cannot
pin to literal quotes.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from i18n.config import Language
from i18n.glossary import Glossary, glossary_prompt
from i18n.validate import Finding

Severity = Literal["blocker", "drift"]


@dataclass(frozen=True)
class SemanticFinding:
    """A reviewer-reported meaning change, anchored to literal quotes from both texts."""

    severity: Severity
    source_span: str
    target_span: str
    explanation: str


def system_prompt(general_prompt: str, language: Language, instructions: str, glossary: Glossary) -> str:
    """The static prefix of every translation call for one language."""
    header = f"# Target language: {language.name} (`{language.code}`)"
    return "\n\n".join(part.strip() for part in (general_prompt, header, instructions, glossary_prompt(glossary)))


def translate_request(english: str) -> str:
    """The user message asking for a whole-page translation."""
    return (
        "Translate the following Markdown page. Return only the translated page.\n\n"
        "<english-page>\n"
        f"{english}"
        "\n</english-page>"
    )


def update_request(english: str, changed: list[str], previous: str) -> str:
    """The user message for retranslating changed sections of an already-translated page."""
    listing = "\n".join(f"- {label}" for label in changed)
    return (
        "This page was translated before and only part of the English changed. Retranslate it,"
        " reproducing the previous translation verbatim everywhere except the changed sections"
        " listed here (a section is the front matter, the introduction before the first `##`"
        " heading, or one `##` heading with everything under it):\n\n"
        f"{listing}\n\n"
        "Current English page:\n\n<english-page>\n"
        f"{english}"
        "\n</english-page>\n\n"
        "Previous translation of the page:\n\n<previous-translation>\n"
        f"{previous}"
        "\n</previous-translation>\n\n"
        "Return only the full translated page."
    )


def repair_request(findings: list[Finding]) -> str:
    """The follow-up message feeding validation failures back for correction."""
    listing = "\n".join(f"- {finding}" for finding in findings)
    return (
        "Your translation broke the following structural rules. Fix each problem and return the"
        " full corrected page, changing nothing else:\n\n"
        f"{listing}"
    )


def nav_request(labels: Sequence[str], reusable: Mapping[str, str]) -> str:
    """The user message asking for every navigation label's rendering as one JSON object.

    `reusable` holds the labels already published with today's prompt inputs;
    it rides along so a new label lands consistent with its neighbours (the
    caller copies those renderings over the reply either way).
    """
    listing = "\n".join(f"{number}. {label}" for number, label in enumerate(labels, start=1))
    request = (
        "Translate the navigation labels of this documentation site's sidebar. Each numbered line"
        " below is one label — a section title or the link text of one page — that a reader sees on"
        " its own, out of context. Render each as a short, natural navigation label in the target"
        " language (a compact noun phrase, never a sentence), applying the glossary and keeping the"
        " listed terms spelled in English exactly as written.\n\n"
        f"{listing}\n\n"
    )
    if reusable:
        published = json.dumps(reusable, ensure_ascii=False, indent=2)
        request += (
            "These labels were translated before. Reuse each of these renderings verbatim, and keep"
            f" the terminology of the new labels consistent with them:\n\n{published}\n\n"
        )
    return request + (
        "Return only a single JSON object mapping every English label above, spelled exactly as"
        " given, to its translation — no other text."
    )


def nav_repair_request(findings: list[Finding]) -> str:
    """The follow-up message feeding label validation failures back for correction."""
    listing = "\n".join(f"- {finding}" for finding in findings)
    return (
        "Your reply broke the following rules. Fix each problem and return the full corrected JSON"
        f" object, changing nothing else:\n\n{listing}"
    )


def semantic_repair_request(findings: list[SemanticFinding]) -> str:
    """The follow-up message asking for a fix of confirmed meaning changes."""
    listing = "\n".join(
        f'- English "{finding.source_span}" was rendered as "{finding.target_span}": {finding.explanation}'
        for finding in findings
    )
    return (
        "A bilingual reviewer found places where your translation changed the meaning of the"
        " English. Correct each one and return the full corrected page, changing nothing else:\n\n"
        f"{listing}"
    )


VERIFY_SYSTEM = """\
You are an adversarial bilingual reviewer of technical documentation. You are shown one \
block of an English page and its machine translation. Your only job is to find places \
where the translation would make a developer believe or do something different from the \
English. Ignore style, tone, register and word order; a fluent paraphrase is not a problem.

Hunt specifically for:
- a dropped or added negation ("must not" becoming "must", "never" disappearing)
- an inverted or altered condition ("unless", "only if", "as long as")
- swapped actors (client vs server, user vs model, caller vs handler)
- reversed cause and effect
- changed obligation strength (must / should / may / cannot)
- a wrong-sense word choice that changes what the reader would do
- an added or removed security-relevant statement

Severity: "blocker" when a reader following the translation would do the wrong thing or \
believe something false; "drift" for a real but harmless meaning shift.

Rules for reporting:
- Quote the exact English words and the exact translated words the problem is in. Both \
quotes must be copied literally from the texts you were given; a finding whose quotes are \
not literal substrings is discarded.
- Do not invent problems. Most blocks are fine, and an empty list is the correct answer for \
them. Never report style preferences, terminology you would render differently, or word order.
- Answer with a JSON array only, no prose. Each element is an object with the keys \
"severity", "source_quote", "target_quote", "explanation" (one sentence).

Calibration:
- English "you should not cache this token" translated with the negation dropped, so it now \
tells the reader to cache it: report {"severity": "blocker", ...}.
- English "the server may retry" rendered as the equivalent of "the server retries" (a \
possibility turned into a certainty): report {"severity": "drift", ...}.
- English "Register the tool before starting the server" rendered as an idiomatic sentence \
with the clauses reordered but the same instruction: report nothing for it."""


def verify_request(english_block: str, translated_block: str) -> str:
    """The user message pairing one English block with its translation."""
    return f"<english>\n{english_block}\n</english>\n\n<translation>\n{translated_block}\n</translation>"


def _json_values(text: str, opener: str) -> Iterator[object]:
    """Every JSON value opening with `opener` embedded in `text` (prose or stray brackets around them ignored).

    A value that decodes from a `[` is an array and from a `{` an object,
    so the opener character picks the shape; a value nested inside an earlier
    one is offered too, since each opener character starts its own decode.
    """
    decoder = json.JSONDecoder()
    start = -1
    while (start := text.find(opener, start + 1)) != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        yield cast("object", value)


def parse_nav_response(text: str) -> dict[str, str] | None:
    """The label map in the reply, or None when it is not a JSON object of string renderings."""
    value = next(_json_values(text, "{"), None)
    if not isinstance(value, dict):
        return None
    entries = cast("dict[str, Any]", value)
    if not all(isinstance(rendering, str) for rendering in entries.values()):
        return None
    return cast("dict[str, str]", entries)


def parse_verify_response(text: str, english_block: str, translated_block: str) -> list[SemanticFinding] | None:
    """Parse the reviewer's JSON findings, dropping those whose quotes are not literal.

    The reply may carry prose around the answer, and prose may hold stray
    JSON of its own (a bare `[]`, a `["note", {...}]` aside), so the answer is
    picked among every array that is entirely finding objects — the longest
    one when several qualify. Returns None when no array qualifies, so the
    caller can tell "no findings" from "unreadable".
    """
    candidates = [findings for value in _json_values(text, "[") if (findings := _findings(value)) is not None]
    if not candidates:
        return None
    # The anti-hallucination filter: both quotes must exist verbatim, line
    # wrapping aside (a quote may run across a hard wrap in the source).
    english, translated = _one_line(english_block), _one_line(translated_block)
    return [
        finding
        for finding in max(candidates, key=len)
        if _one_line(finding.source_span) in english and _one_line(finding.target_span) in translated
    ]


def _findings(value: object) -> list[SemanticFinding] | None:
    """`value` as a list of findings, or None if it is not an array made only of finding objects."""
    if not isinstance(value, list):
        return None
    findings: list[SemanticFinding] = []
    for entry in cast("list[object]", value):
        if not isinstance(entry, dict):
            return None
        fields = cast("dict[str, Any]", entry)
        severity = fields.get("severity")
        source_span, target_span = fields.get("source_quote"), fields.get("target_quote")
        explanation = fields.get("explanation", "")
        if severity not in ("blocker", "drift"):
            return None
        if not (isinstance(source_span, str) and isinstance(target_span, str) and isinstance(explanation, str)):
            return None
        findings.append(SemanticFinding(severity, source_span, target_span, explanation))
    return findings


def _one_line(text: str) -> str:
    """`text` with every run of whitespace (line breaks included) collapsed to one space."""
    return " ".join(text.split())
