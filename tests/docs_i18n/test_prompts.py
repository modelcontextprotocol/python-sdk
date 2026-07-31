"""Tests for prompt assembly and the semantic-review parser (i18n/prompts.py)."""

import json

from i18n.glossary import Glossary, Term
from i18n.prompts import (
    SemanticFinding,
    nav_request,
    parse_nav_response,
    parse_verify_response,
    system_prompt,
    update_request,
)
from tests.docs_i18n._repo import LANGUAGE


def test_system_prompt_orders_general_then_language_then_instructions_then_glossary() -> None:
    glossary = Glossary(("MCP",), (Term("tool", "tuul"),))

    prompt = system_prompt("GENERAL RULES", LANGUAGE, "INSTRUCTIONS BODY", glossary)

    assert prompt.index("GENERAL RULES") < prompt.index("Testish") < prompt.index("INSTRUCTIONS BODY")
    assert prompt.index("INSTRUCTIONS BODY") < prompt.index("- tool → tuul")


def test_update_request_lists_changed_sections_and_prior_translation() -> None:
    message = update_request("ENGLISH PAGE", ["front matter", "## Two {#two}"], "PRIOR PAGE")

    assert message.index("- front matter") < message.index("- ## Two {#two}") < message.index("ENGLISH PAGE")
    assert message.index("ENGLISH PAGE") < message.index("PRIOR PAGE")


def test_parse_verify_response_keeps_literal_quotes_and_drops_the_rest() -> None:
    english = "You must not cache the token."
    translated = "Sie muessen das Token cachen."
    reply = "Findings:\n" + json.dumps(
        [
            {
                "severity": "blocker",
                "source_quote": "must not cache",
                "target_quote": "muessen das Token cachen",
                "explanation": "negation dropped",
            },
            {
                "severity": "drift",
                "source_quote": "invented words",
                "target_quote": "cachen",
                "explanation": "not a real quote",
            },
        ]
    )

    findings = parse_verify_response(reply, english, translated)

    assert findings == [SemanticFinding("blocker", "must not cache", "muessen das Token cachen", "negation dropped")]


def test_parse_verify_response_accepts_an_empty_list() -> None:
    assert parse_verify_response("[]", "a", "b") == []


def test_parse_verify_response_finds_the_array_among_stray_brackets() -> None:
    finding = {"severity": "drift", "source_quote": "a", "target_quote": "b", "explanation": "see [1]"}
    reply = f"As noted [above], the review (part [i]) follows: {json.dumps([finding])} — end of [review]."

    assert parse_verify_response(reply, "a", "b") == [SemanticFinding("drift", "a", "b", "see [1]")]


def test_parse_verify_response_picks_the_findings_array_over_stray_json_in_the_prose() -> None:
    finding = {"severity": "drift", "source_quote": "a", "target_quote": "b", "explanation": "shifted"}
    # An empty array in the prose no longer reads as "no findings", and an
    # aside array mixing prose with a finding object is not the answer either.
    prose_before = f"My first pass found [] worth reporting, then: {json.dumps([finding])}"
    mixed_aside = f'A side note: ["heads-up", {json.dumps(finding)}]. Findings: {json.dumps([finding])}'

    for reply in (prose_before, mixed_aside):
        assert parse_verify_response(reply, "a", "b") == [SemanticFinding("drift", "a", "b", "shifted")]


def test_parse_verify_response_returns_none_when_only_a_mixed_array_is_present() -> None:
    finding = {"severity": "drift", "source_quote": "a", "target_quote": "b", "explanation": "shifted"}
    reply = f'Notes: ["heads-up", {json.dumps(finding)}]'

    assert parse_verify_response(reply, "a", "b") is None


def test_parse_verify_response_matches_quotes_across_hard_wrapping() -> None:
    english = "The client must not\ncache this token between\nrequests."
    translated = "Der Client darf dieses Token\nzwischen Anfragen nicht cachen."
    reply = json.dumps(
        [
            {
                "severity": "blocker",
                "source_quote": "must not cache this token between requests",
                "target_quote": "darf dieses Token zwischen Anfragen nicht cachen",
                "explanation": "checking the wrapped quote",
            }
        ]
    )

    findings = parse_verify_response(reply, english, translated)

    assert findings is not None and len(findings) == 1
    # The quote is kept as the reviewer wrote it, not re-wrapped.
    assert findings[0].source_span == "must not cache this token between requests"


def test_parse_verify_response_returns_none_for_unusable_replies() -> None:
    assert parse_verify_response("no json here", "a", "b") is None
    assert parse_verify_response("[{broken", "a", "b") is None
    assert (
        parse_verify_response(
            '[{"severity": "meh", "source_quote": "a", "target_quote": "b", "explanation": ""}]', "a", "b"
        )
        is None
    )
    assert parse_verify_response('[{"severity": "drift", "source_quote": 1, "target_quote": "b"}]', "a", "b") is None
    assert parse_verify_response("[1]", "a", "b") is None


def test_nav_request_numbers_the_labels_and_carries_the_published_renderings() -> None:
    request = nav_request(["Get started", "Installation"], {"Get started": "はじめに"})

    assert "1. Get started\n2. Installation" in request
    assert '"Get started": "はじめに"' in request and request.index("2. Installation") < request.index("はじめに")
    assert "single JSON object" in request
    assert "translated before" not in nav_request(["Get started"], {})


def test_parse_nav_response_reads_the_object_and_rejects_non_string_renderings() -> None:
    assert parse_nav_response('Sure: {"Home": "Startseite", "Tools": ""} — done.') == {
        "Home": "Startseite",
        "Tools": "",
    }
    assert parse_nav_response('{"Home": 3}') is None
    assert parse_nav_response("no object here") is None
    assert parse_nav_response('["Home"]') is None
