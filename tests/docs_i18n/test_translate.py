"""Tests for the per-page translation pipeline (i18n/translate.py), driven by a scripted model."""

import json

from i18n.glossary import Glossary
from i18n.inputs import LanguageInputs
from i18n.nav import NavState, NavTranslation, labels_hash
from i18n.pages import block_hashes, split_blocks
from i18n.state import PageState
from i18n.translate import (
    MAX_OUTPUT_TOKENS,
    MIN_OUTPUT_TOKENS,
    THINKING_ALLOWANCE_TOKENS,
    RunContext,
    build_nav_prompt,
    build_prompt,
    mechanical_repair,
    output_budget,
    translate_nav,
    translate_page,
)
from tests.docs_i18n._repo import ENGLISH, LANGUAGE, TRANSLATED, FakeTranslator, nav_reply

INPUTS = LanguageInputs(LANGUAGE, "GENERAL", "INSTRUCTIONS", Glossary(("MCP", "Context"), ()), "gh", "ih", "lh")

SHORT_ENGLISH = "# Cache {#cache}\n\nYou must not cache the token.\n"
SHORT_TRANSLATED = "# Kesh {#cache}\n\nDu darfst das Token niemals cachen.\n"


def _context(fake: FakeTranslator, *, verify: bool = False) -> RunContext:
    return RunContext(fake, "model-t", "model-v", verify, "commit123", "2026-07-30T00:00:00Z")


def _record(english: str) -> PageState:
    blocks = split_blocks(english)
    return PageState(
        source_commit="old",
        source_hash="old",
        blocks=tuple(block_hashes(blocks, INPUTS.salt)),
        general_prompt_hash="gh",
        instructions_hash="ih",
        glossary_hash="lh",
        model="model-t",
        translated_at="2026-07-01T00:00:00Z",
    )


def test_translate_page_whole_page_writes_translation_and_state() -> None:
    fake = FakeTranslator([TRANSLATED])

    result = translate_page("tools.md", ENGLISH, INPUTS, _context(fake), previous=None, previous_state=None)

    assert result.text == TRANSLATED and result.ok
    assert result.state is not None
    assert result.state.model == "model-t" and result.state.source_commit == "commit123"
    assert result.state.blocks == tuple(block_hashes(split_blocks(ENGLISH), INPUTS.salt))
    (call,) = fake.calls
    assert "INSTRUCTIONS" in call.system and "- MCP" in call.system
    assert call.messages[0].role == "user" and ENGLISH in call.messages[0].content


def test_translate_page_retries_with_validation_findings_fed_back() -> None:
    broken = TRANSLATED.split("## Ein tuul")[0]
    fake = FakeTranslator([broken, TRANSLATED])

    result = translate_page("tools.md", ENGLISH, INPUTS, _context(fake), previous=None, previous_state=None)

    assert result.text == TRANSLATED
    retry = fake.calls[1].messages
    assert retry[1].role == "assistant" and retry[1].content == broken
    assert "blocks" in retry[2].content and retry[2].role == "user"


def test_translate_page_fails_after_three_attempts_and_reports_findings() -> None:
    broken = "# Only a title {#tools}\n"
    fake = FakeTranslator([broken, broken, broken])

    result = translate_page("tools.md", ENGLISH, INPUTS, _context(fake), previous=None, previous_state=None)

    assert result.text is None and result.state is None
    assert result.findings and len(fake.calls) == 3


def test_mechanical_repair_restores_anchors_code_and_unwraps_without_a_retry() -> None:
    mangled = (
        "```markdown\n"
        + TRANSLATED.replace(" {#tools}", "")
        .replace(" {#registering-a-tool}", "")
        .replace('--8<-- "docs_src/tools/tutorial001.py"', "print('translated code')")
        .rstrip("\n")
        + "\n```\n"
    )

    assert mechanical_repair(ENGLISH, mangled) == TRANSLATED
    fake = FakeTranslator([mangled])
    result = translate_page("tools.md", ENGLISH, INPUTS, _context(fake), previous=None, previous_state=None)
    assert result.text == TRANSLATED and len(fake.calls) == 1


def test_mechanical_repair_unwraps_a_longer_page_fence_carrying_an_info_string() -> None:
    # A four-backtick wrapper with an info string, so the page's own three-backtick fences read as content.
    wrapped = "````markdown\n" + TRANSLATED + "````\n"

    assert mechanical_repair(ENGLISH, wrapped) == TRANSLATED
    # A tilde wrapper unwraps the same way; a page that opens with a fence in English is left alone.
    assert mechanical_repair(ENGLISH, "~~~\n" + TRANSLATED + "~~~\n") == TRANSLATED
    fenced_english = "```py\nprint(1)\n```\n"
    assert mechanical_repair(fenced_english, fenced_english) == fenced_english


def test_unclosed_output_fence_is_never_spliced_over_and_drives_a_retry() -> None:
    english = "# T {#t}\n\n```py\nprint(1)\n```\n\nTail prose.\n"
    unclosed = "# T {#t}\n\n```py\nprint(1)\n\nSchwanz prosa.\n"  # the model forgot the closer
    fixed = "# T {#t}\n\n```py\nprint(1)\n```\n\nSchwanz prosa.\n"

    # No lossy repair: the reply comes back untouched (its tail prose intact) ...
    assert mechanical_repair(english, unclosed) == unclosed
    # ... and the finding drives a retry that yields the closed page.
    fake = FakeTranslator([unclosed, fixed])
    result = translate_page("t.md", english, INPUTS, _context(fake), previous=None, previous_state=None)
    assert result.text == fixed
    assert "code block 1 is not closed" in fake.calls[1].messages[-1].content


def test_appending_a_section_marks_only_the_new_block_changed_and_tiles_the_page() -> None:
    v1 = "# T {#t}\n\nIntro.\n\n## A {#a}\n\nA body.\n\n## B {#b}\n\nB body.\n\n## C {#c}\n\nC body.\n"
    prior = "# T {#t}\n\nEinleitung.\n\n## A {#a}\n\nA Text.\n\n## B {#b}\n\nB Text.\n\n## C {#c}\n\nC Text.\n"
    v2 = v1 + "\n## D {#d}\n\nD body.\n"
    # The model returns the new page but rephrases the untouched last section C.
    reply = prior.replace("C Text.", "C anders formuliert.") + "\n## D {#d}\n\nD Text.\n"

    prompt = build_prompt(v2, INPUTS, prior, _record(v1))
    assert prompt.mode == "update" and prompt.changed == [4]

    fake = FakeTranslator([reply])
    result = translate_page("p.md", v2, INPUTS, _context(fake), previous=prior, previous_state=_record(v1))
    # Every prior block, and the blank line separating C from the new D, survives byte-for-byte.
    assert result.text == prior + "\n## D {#d}\n\nD Text.\n"


def test_output_budget_reserves_a_thinking_allowance_within_the_floor_and_cap() -> None:
    assert output_budget("short page") == MIN_OUTPUT_TOKENS
    medium = "x" * 10_000
    assert output_budget(medium) == 10_000 + THINKING_ALLOWANCE_TOKENS
    assert output_budget("x" * 200_000) == MAX_OUTPUT_TOKENS


def test_translate_page_update_mode_carries_unchanged_blocks_forward_verbatim() -> None:
    prior = TRANSLATED
    edited_english = ENGLISH.replace("MCP tools are functions", "MCP tools are asynchronous functions")
    # The model rephrases the unchanged section even though only the intro changed.
    rephrased = TRANSLATED.replace("Xx MCP tuulzen zint", "Xx MCP tuulzen zint asynchron").replace(
        "objekt zint immer verfuegbar", "objekt ist stets bereit"
    )
    fake = FakeTranslator([rephrased])

    result = translate_page(
        "tools.md", edited_english, INPUTS, _context(fake), previous=prior, previous_state=_record(ENGLISH)
    )

    assert result.text is not None
    assert "asynchron" in result.text
    assert "objekt ist stets bereit" not in result.text and "objekt zint immer verfuegbar" in result.text
    (call,) = fake.calls
    assert "- introduction (before the first `##` heading)" in call.messages[0].content
    assert prior in call.messages[0].content


def test_build_prompt_falls_back_to_whole_page_when_prior_and_state_disagree() -> None:
    prompt = build_prompt(ENGLISH, INPUTS, "# only a fragment\n", _record(ENGLISH))

    assert prompt.mode == "whole page" and prompt.changed == list(range(len(split_blocks(ENGLISH))))


def test_semantic_gate_blocker_repaired_on_second_round_passes() -> None:
    blocker = json.dumps(
        [
            {
                "severity": "blocker",
                "source_quote": "must not cache",
                "target_quote": "das Token immer cachen",
                "explanation": "negation lost",
            }
        ]
    )
    wrong = "# Kesh {#cache}\n\nDu darfst das Token immer cachen.\n"
    fake = FakeTranslator([wrong, blocker, SHORT_TRANSLATED, "[]"])

    result = translate_page(
        "cache.md", SHORT_ENGLISH, INPUTS, _context(fake, verify=True), previous=None, previous_state=None
    )

    assert result.text == SHORT_TRANSLATED and result.blockers == []
    assert fake.calls[1].model == "model-v" and "negation lost" in fake.calls[2].messages[-1].content


def test_semantic_gate_blocker_that_survives_repair_fails_the_page() -> None:
    blocker = json.dumps(
        [
            {
                "severity": "blocker",
                "source_quote": "must not cache",
                "target_quote": "das Token immer cachen",
                "explanation": "negation lost",
            }
        ]
    )
    wrong = "# Kesh {#cache}\n\nDu darfst das Token immer cachen.\n"
    fake = FakeTranslator([wrong, blocker, wrong, blocker])

    result = translate_page(
        "cache.md", SHORT_ENGLISH, INPUTS, _context(fake, verify=True), previous=None, previous_state=None
    )

    assert result.text is None and result.blockers and result.blockers[0].severity == "blocker"


def test_semantic_gate_drift_is_reported_but_passes() -> None:
    drift = json.dumps(
        [
            {
                "severity": "drift",
                "source_quote": "must not",
                "target_quote": "darfst",
                "explanation": "softened obligation",
            }
        ]
    )
    fake = FakeTranslator([SHORT_TRANSLATED, drift])

    result = translate_page(
        "cache.md", SHORT_ENGLISH, INPUTS, _context(fake, verify=True), previous=None, previous_state=None
    )

    assert result.text == SHORT_TRANSLATED and len(result.drifts) == 1


def test_semantic_gate_unparseable_reply_twice_is_an_error() -> None:
    fake = FakeTranslator([SHORT_TRANSLATED, "no json", "still none"])

    result = translate_page(
        "cache.md", SHORT_ENGLISH, INPUTS, _context(fake, verify=True), previous=None, previous_state=None
    )

    assert result.text is None and result.error is not None and "unparseable" in result.error


NAV_LABELS = ["Get started", "The Context", "Servers"]


def _nav(labels: dict[str, str], **hashes: str) -> NavTranslation:
    state = NavState(
        labels_hash=labels_hash(list(labels)),
        general_prompt_hash=hashes.get("general_prompt_hash", "gh"),
        instructions_hash=hashes.get("instructions_hash", "ih"),
        glossary_hash=hashes.get("glossary_hash", "lh"),
        model="model-t",
        translated_at="2026-07-01T00:00:00Z",
    )
    return NavTranslation(labels=dict(labels), state=state)


def test_translate_nav_writes_the_label_map_and_state_from_one_call() -> None:
    fake = FakeTranslator([nav_reply({"Get started": "Los", "The Context": "Der Context", "Servers": "Server"})])

    result = translate_nav(NAV_LABELS, INPUTS, _context(fake), previous=None)

    assert result.nav is not None and result.ok
    assert result.nav.labels == {"Get started": "Los", "The Context": "Der Context", "Servers": "Server"}
    assert result.nav.state.labels_hash == labels_hash(NAV_LABELS) and result.nav.state.model == "model-t"
    (call,) = fake.calls
    assert "INSTRUCTIONS" in call.system and "- MCP" in call.system
    assert "1. Get started\n2. The Context\n3. Servers" in call.messages[0].content


def test_translate_nav_retries_with_the_findings_fed_back() -> None:
    incomplete = nav_reply({"Get started": "Los", "Servers": "Server"})
    complete = nav_reply({"Get started": "Los", "The Context": "Der Context", "Servers": "Server"})
    fake = FakeTranslator([incomplete, complete])

    result = translate_nav(NAV_LABELS, INPUTS, _context(fake), previous=None)

    assert result.ok and len(fake.calls) == 2
    retry = fake.calls[1].messages
    assert retry[1].content == incomplete
    assert "missing renderings for the labels ['The Context']" in retry[2].content


def test_translate_nav_fails_after_three_attempts_and_reports_findings() -> None:
    bad = nav_reply({"Get started": "Los", "The Context": "Der Kontext", "Servers": "Server"})
    fake = FakeTranslator([bad, bad, bad])

    result = translate_nav(NAV_LABELS, INPUTS, _context(fake), previous=None)

    assert result.nav is None and len(fake.calls) == 3
    assert any("'Context' must appear verbatim" in str(finding) for finding in result.findings)


def test_translate_nav_carries_unchanged_labels_forward_byte_for_byte() -> None:
    previous = _nav({"Get started": "Los geht's", "The Context": "Der Context"})
    # The model rephrases the stable labels; only the new "Servers" survives from its reply.
    reply = nav_reply({"Get started": "Anfangen", "The Context": "Über Context", "Servers": "Server"})
    fake = FakeTranslator([reply])

    result = translate_nav(NAV_LABELS, INPUTS, _context(fake), previous=previous)

    assert result.nav is not None
    assert result.nav.labels == {"Get started": "Los geht's", "The Context": "Der Context", "Servers": "Server"}
    prompt = build_nav_prompt(NAV_LABELS, INPUTS, previous)
    assert prompt.mode == "update" and prompt.changed == [2]
    assert '"Get started": "Los geht\'s"' in fake.calls[0].messages[0].content


def test_translate_nav_after_a_glossary_change_retranslates_every_label() -> None:
    previous = _nav({"Get started": "Los geht's", "The Context": "Der Context"}, glossary_hash="stale")
    reply = nav_reply({"Get started": "Anfangen", "The Context": "Über Context", "Servers": "Server"})
    fake = FakeTranslator([reply])

    result = translate_nav(NAV_LABELS, INPUTS, _context(fake), previous=previous)

    assert result.nav is not None
    assert result.nav.labels == {"Get started": "Anfangen", "The Context": "Über Context", "Servers": "Server"}
    assert build_nav_prompt(NAV_LABELS, INPUTS, previous).mode == "whole map"
