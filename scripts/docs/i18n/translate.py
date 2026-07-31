"""Translate one page, or a language's navigation labels, through the same funnel.

Two prompt modes for a page: with no translation it gets a whole-page
request; with a prior translation it gets the current English, the prior
text, and the list of sections whose English changed. Either way the reply
then goes through one funnel — invariants the model reliably fumbles (heading
anchors, code fence contents) are re-imposed positionally from the English
source instead of retried, unchanged sections are copied byte-for-byte from
the prior translation (the model rephrases stable text even when told not
to; the copy is what makes corrections permanent), the structural validator
gates the result with its findings fed back on retry, and a stronger model
reviews the freshly written blocks for meaning changes. The nav labels ride
the same loop in miniature: one call over the label list, labels already
rendered with today's prompt inputs copied over the reply, and the label
validator's findings fed back on retry (no semantic gate for one-to-four-word
labels).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from i18n.client import Message, Translator, TranslatorError
from i18n.config import NAV_FILE
from i18n.inputs import LanguageInputs
from i18n.markdown import anchor_source_form, fence_line_ranges, parse_headings
from i18n.nav import NavState, NavTranslation
from i18n.pages import Block, block_hashes, page_text, sha256, split_blocks
from i18n.prompts import (
    VERIFY_SYSTEM,
    SemanticFinding,
    nav_repair_request,
    nav_request,
    parse_nav_response,
    parse_verify_response,
    repair_request,
    semantic_repair_request,
    system_prompt,
    translate_request,
    update_request,
    verify_request,
)
from i18n.state import PageState
from i18n.validate import Finding, validate_nav_labels, validate_page

# One attempt plus the retries that feed validation errors back.
ATTEMPTS = 3

# Output-token budgets. The models think before answering and thinking
# tokens count against `max_tokens`, so every call carries a fixed thinking
# allowance on top of what the reply itself needs; a page never gets less
# than the floor and never more than the cap. The reviewer answers a short
# JSON list, so its whole budget is thinking allowance.
THINKING_ALLOWANCE_TOKENS = 12_000
MIN_OUTPUT_TOKENS = 16_000
MAX_OUTPUT_TOKENS = 64_000
VERIFY_MAX_TOKENS = 16_000

# A whole page wrapped in one code fence: an opener of three or more
# backticks/tildes with any info string (```` ```markdown ````), and a matching
# closer on the last line. Models add this despite instructions.
_WRAPPER = re.compile(
    r"\A(?P<opener>`{3,}|~{3,})[ \t]*[^\n]*\n(?P<body>.*)\n(?P<closer>`{3,}|~{3,})[ \t]*\n?\Z",
    flags=re.DOTALL,
)
# The finding fed back when the nav reply is not the requested JSON object.
_NAV_REPLY_SHAPE = "reply must be one JSON object mapping each English label to its rendering (a non-empty string)"


@dataclass(frozen=True)
class Prompt:
    """The assembled model request for one page; `changed` lists the block indices being (re)written."""

    system: str
    messages: list[Message]
    changed: list[int]
    mode: str


@dataclass(frozen=True)
class RunContext:
    """The moving parts a translation run needs beyond the page itself."""

    translator: Translator
    model: str
    verify_model: str
    verify: bool
    source_commit: str
    now: str


@dataclass
class PageResult:
    """The outcome of translating one page; `text`/`state` are set only when it passed."""

    page: str
    text: str | None = None
    state: PageState | None = None
    findings: list[Finding] = field(default_factory=list[Finding])
    blockers: list[SemanticFinding] = field(default_factory=list[SemanticFinding])
    drifts: list[SemanticFinding] = field(default_factory=list[SemanticFinding])
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.text is not None


@dataclass
class NavResult:
    """The outcome of translating the nav labels; `nav` is set only when it passed."""

    nav: NavTranslation | None = None
    findings: list[Finding] = field(default_factory=list[Finding])
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.nav is not None


def build_prompt(
    english: str, inputs: LanguageInputs, previous: str | None, previous_state: PageState | None
) -> Prompt:
    """Assemble the request for a page: whole-page, or an update marking the changed blocks."""
    system = system_prompt(inputs.general_prompt, inputs.language, inputs.instructions, inputs.glossary)
    blocks = split_blocks(english)
    changed = _changed_blocks(blocks, inputs, previous, previous_state)
    if changed is None or previous is None:
        return Prompt(system, [Message("user", translate_request(english))], list(range(len(blocks))), "whole page")
    labels = [blocks[index].label for index in changed]
    return Prompt(system, [Message("user", update_request(english, labels, previous))], changed, "update")


def _changed_blocks(
    blocks: list[Block], inputs: LanguageInputs, previous: str | None, previous_state: PageState | None
) -> list[int] | None:
    """Indices of the blocks that need translating; None means the whole page does.

    A block is unchanged when its salted hash was recorded last time and the
    prior translation still splits into the recorded number of blocks, so a
    stale or hand-mangled prior file falls back to whole-page mode.
    """
    if previous is None or previous_state is None:
        return None
    if len(split_blocks(previous)) != len(previous_state.blocks):
        return None
    recorded = set(previous_state.blocks)
    hashes = block_hashes(blocks, inputs.salt)
    return [index for index, digest in enumerate(hashes) if digest not in recorded]


def carry_forward(
    english: str, output: str, inputs: LanguageInputs, previous: str | None, previous_state: PageState | None
) -> str:
    """Overwrite every unchanged block of `output` with the prior translated block, byte-for-byte."""
    blocks = split_blocks(english)
    if _changed_blocks(blocks, inputs, previous, previous_state) is None or previous is None or previous_state is None:
        return output
    output_blocks = split_blocks(output)
    if len(output_blocks) != len(blocks):
        return output
    prior_blocks = split_blocks(previous)
    prior_by_hash = dict(zip(previous_state.blocks, prior_blocks, strict=True))
    kept = [
        prior_by_hash.get(digest, translated)
        for digest, translated in zip(block_hashes(blocks, inputs.salt), output_blocks, strict=True)
    ]
    return page_text(kept)


def mechanical_repair(english: str, output: str) -> str:
    """Fix what the model cannot be trusted to reproduce: unwrap, heading anchors, code contents."""
    return _repair_fences(english, _repair_anchors(english, _unwrap(english, output)))


def _unwrap(english: str, output: str) -> str:
    """Drop a code fence the model wrapped the whole page in, and match the trailing newline."""
    match = None if english.startswith(("```", "~~~")) else _WRAPPER.match(output)
    if match and match["closer"][0] == match["opener"][0] and len(match["closer"]) >= len(match["opener"]):
        output = match["body"]
    if english.endswith("\n") and not output.endswith("\n"):
        output += "\n"
    return output


def _repair_anchors(english: str, output: str) -> str:
    """Re-impose the English heading anchors positionally when the heading counts agree.

    Each heading is rewritten to the one canonical spelling — its translated
    text, then the English heading's rendered id in source form
    (`## <text> {#id}`) — unless it already reads exactly that way, so a wrong
    id, a right id spelled differently (`{#foo_bar}` for the source's
    `{#foo\\_bar}`), and a block glued to CJK text without the space attr_list
    needs all come out the same: the form the validator reads by and the
    anchor check writes by.
    """
    expected, found = parse_headings(english), parse_headings(output)
    if len(expected) != len(found):
        return output
    lines = output.split("\n")
    for want, got in zip(expected, found, strict=True):
        if want.anchor is None:
            continue
        canonical = f"{'#' * got.level} {got.text} {{#{anchor_source_form(want.anchor)}}}"
        if lines[got.line] != canonical:
            lines[got.line] = canonical
    return "\n".join(lines)


def _repair_fences(english: str, output: str) -> str:
    """Re-impose the English code fence bodies positionally when the fence counts agree.

    An unclosed fence in the output is left alone: its body runs to the end of
    the page, so splicing the English body over it would silently drop the
    prose that followed. The validator reports it and drives a retry instead.
    """
    source_lines, output_lines = english.split("\n"), output.split("\n")
    expected = list(fence_line_ranges(source_lines))
    found = list(fence_line_ranges(output_lines))
    if len(expected) != len(found) or not all(fence.closed for fence in found):
        return output
    result: list[str] = []
    cursor = 0
    for want, got in zip(expected, found, strict=True):
        result += output_lines[cursor : got.opener + 1]
        result += [source_lines[index] for index in want.body]
        cursor = got.closer
    result += output_lines[cursor:]
    return "\n".join(result)


def output_budget(english: str) -> int:
    """Output tokens for a page: room for a reply as long as the page plus thinking, floor to cap."""
    return min(MAX_OUTPUT_TOKENS, max(MIN_OUTPUT_TOKENS, len(english) + THINKING_ALLOWANCE_TOKENS))


def translate_page(
    page: str,
    english: str,
    inputs: LanguageInputs,
    context: RunContext,
    *,
    previous: str | None,
    previous_state: PageState | None,
) -> PageResult:
    """Translate one page end to end; the result carries either a translation or the reasons it failed."""
    prompt = build_prompt(english, inputs, previous, previous_state)
    messages = list(prompt.messages)
    result = PageResult(page)
    output = ""
    findings: list[Finding] = []
    script = inputs.language.script
    try:
        for attempt in range(ATTEMPTS):
            if attempt:
                messages += [Message("assistant", output), Message("user", repair_request(findings))]
            output = _funnel(english, inputs, prompt, messages, context, previous, previous_state)
            findings = validate_page(page, english, output, inputs.glossary, script=script)
            if not findings:
                break
        else:
            result.findings = findings
            return result

        if context.verify:
            review = _reviewer(prompt.changed, context)
            blockers, result.drifts = review(english, output)
            if blockers:
                # One repair round; a blocker that survives it fails the page.
                messages += [Message("assistant", output), Message("user", semantic_repair_request(blockers))]
                output = _funnel(english, inputs, prompt, messages, context, previous, previous_state)
                if findings := validate_page(page, english, output, inputs.glossary, script=script):
                    result.findings, result.blockers = findings, blockers
                    return result
                blockers, result.drifts = review(english, output)
                if blockers:
                    result.blockers = blockers
                    return result
    except TranslatorError as exc:
        result.error = str(exc)
        return result

    blocks = split_blocks(english)
    result.text = output
    result.state = PageState(
        source_commit=context.source_commit,
        source_hash=sha256(english),
        blocks=tuple(block_hashes(blocks, inputs.salt)),
        general_prompt_hash=inputs.general_prompt_hash,
        instructions_hash=inputs.instructions_hash,
        glossary_hash=inputs.glossary_hash,
        model=context.model,
        translated_at=context.now,
    )
    return result


def build_nav_prompt(labels: Sequence[str], inputs: LanguageInputs, previous: NavTranslation | None) -> Prompt:
    """Assemble the request for a language's nav labels; `changed` lists the labels being (re)written."""
    system = system_prompt(inputs.general_prompt, inputs.language, inputs.instructions, inputs.glossary)
    reusable = _reusable_labels(labels, inputs, previous)
    changed = [index for index, label in enumerate(labels) if label not in reusable]
    mode = "update" if reusable else "whole map"
    return Prompt(system, [Message("user", nav_request(labels, reusable))], changed, mode)


def _reusable_labels(labels: Sequence[str], inputs: LanguageInputs, previous: NavTranslation | None) -> dict[str, str]:
    """The prior renderings that carry forward: only those made with today's prompt inputs.

    A general-prompt, instructions or glossary change re-asks every label,
    the same way the salted block hashes re-ask a whole page; only labels
    added to the nav since a still-valid map are new work.
    """
    if previous is None:
        return {}
    made_with = (previous.state.general_prompt_hash, previous.state.instructions_hash, previous.state.glossary_hash)
    if made_with != (inputs.general_prompt_hash, inputs.instructions_hash, inputs.glossary_hash):
        return {}
    return {label: previous.labels[label] for label in labels if label in previous.labels}


def translate_nav(
    labels: Sequence[str], inputs: LanguageInputs, context: RunContext, *, previous: NavTranslation | None
) -> NavResult:
    """Translate the nav label list end to end; the result carries the map or the reasons it failed.

    Labels already rendered with the current prompt inputs are copied over the
    model's reply byte-for-byte, so a retranslation only ever changes new
    labels or answers a changed instruction.
    """
    prompt = build_nav_prompt(labels, inputs, previous)
    reusable = _reusable_labels(labels, inputs, previous)
    messages = list(prompt.messages)
    result = NavResult()
    reply = ""
    translated: dict[str, str] = {}
    findings: list[Finding] = []
    try:
        for attempt in range(ATTEMPTS):
            if attempt:
                messages += [Message("assistant", reply), Message("user", nav_repair_request(findings))]
            # The label map is a short reply: the whole floor budget is thinking allowance.
            reply = context.translator.complete(
                model=context.model, system=prompt.system, messages=messages, max_tokens=MIN_OUTPUT_TOKENS
            )
            parsed = parse_nav_response(reply)
            if parsed is None:
                findings = [Finding(NAV_FILE, None, "labels", _NAV_REPLY_SHAPE)]
                continue
            translated = {**parsed, **reusable}
            findings = validate_nav_labels(NAV_FILE, labels, translated, inputs.glossary)
            if not findings:
                break
        else:
            result.findings = findings
            return result
    except TranslatorError as exc:
        result.error = str(exc)
        return result

    result.nav = NavTranslation(
        labels={label: translated[label] for label in labels},
        state=NavState(
            labels_hash=inputs.nav_fingerprint(labels).labels_hash,
            general_prompt_hash=inputs.general_prompt_hash,
            instructions_hash=inputs.instructions_hash,
            glossary_hash=inputs.glossary_hash,
            model=context.model,
            translated_at=context.now,
        ),
    )
    return result


def _reviewer(
    changed: list[int], context: RunContext
) -> Callable[[str, str], tuple[list[SemanticFinding], list[SemanticFinding]]]:
    """The semantic gate bound to this run's reviewer model, over the changed blocks."""

    def review(english: str, translated: str) -> tuple[list[SemanticFinding], list[SemanticFinding]]:
        return semantic_gate(english, translated, changed, translator=context.translator, model=context.verify_model)

    return review


def _funnel(
    english: str,
    inputs: LanguageInputs,
    prompt: Prompt,
    messages: list[Message],
    context: RunContext,
    previous: str | None,
    previous_state: PageState | None,
) -> str:
    """One model call plus the deterministic post-processing every reply goes through."""
    reply = context.translator.complete(
        model=context.model, system=prompt.system, messages=messages, max_tokens=output_budget(english)
    )
    repaired = mechanical_repair(english, reply)
    return carry_forward(english, repaired, inputs, previous, previous_state)


def semantic_gate(
    english: str, translated: str, changed: list[int], *, translator: Translator, model: str
) -> tuple[list[SemanticFinding], list[SemanticFinding]]:
    """Review each listed block of `translated` against `english`; returns `(blockers, drifts)`.

    Both texts must split into the same blocks (structural validation guarantees
    it before the gate runs).

    Raises:
        TranslatorError: The reviewer's reply was unparseable twice.
    """
    source_blocks, output_blocks = split_blocks(english), split_blocks(translated)
    blockers: list[SemanticFinding] = []
    drifts: list[SemanticFinding] = []
    for index in changed:
        source, output = source_blocks[index].text, output_blocks[index].text
        if not source.strip() or source.strip() == output.strip():
            continue
        for _ in range(2):
            reply = translator.complete(
                model=model,
                system=VERIFY_SYSTEM,
                messages=[Message("user", verify_request(source, output))],
                max_tokens=VERIFY_MAX_TOKENS,
            )
            if (found := parse_verify_response(reply, source, output)) is not None:
                break
        else:
            raise TranslatorError(f"semantic reviewer gave an unparseable reply for block {index}")
        blockers += [finding for finding in found if finding.severity == "blocker"]
        drifts += [finding for finding in found if finding.severity == "drift"]
    return blockers, drifts
