"""Tests for the structural validator (i18n/validate.py): every check passing and failing."""

from i18n.glossary import Glossary, Term
from i18n.validate import Finding, validate_nav_labels, validate_page, validate_page_standalone
from tests.docs_i18n._repo import ENGLISH, TRANSLATED

GLOSSARY = Glossary(keep_in_source_language=("MCP", "Context"), terms=())
# A run the model left untranslated: more than fifteen consecutive English words.
ENGLISH_RUN = " ".join(["these words were simply left standing in the middle of the text"] * 3)


def _checks(findings: list[Finding]) -> set[str]:
    return {finding.check for finding in findings}


def test_faithful_translation_has_no_findings() -> None:
    assert validate_page("tools.md", ENGLISH, TRANSLATED, GLOSSARY, script="latin") == []


def test_missing_section_reports_a_block_shape_finding() -> None:
    truncated = TRANSLATED.split("## Ein tuul")[0]

    findings = validate_page("tools.md", ENGLISH, truncated, GLOSSARY, script="latin")

    assert findings[0].check == "blocks" and findings[0].block is None


def test_changed_anchor_is_reported_on_its_block() -> None:
    broken = TRANSLATED.replace("{#registering-a-tool}", "{#wrong}")

    findings = validate_page("tools.md", ENGLISH, broken, GLOSSARY, script="latin")

    (finding,) = findings
    assert finding.check == "headings" and finding.block == 1
    assert "anchor is {#wrong}, expected {#registering-a-tool}" in finding.message


def test_changed_subheading_level_is_reported() -> None:
    source = "# T {#t}\n\n### Sub {#sub}\n"
    output = "# T {#t}\n\n#### Sub {#sub}\n"

    findings = validate_page("t.md", source, output, GLOSSARY, script="latin")

    assert any("level 4, expected level 3" in f.message for f in findings if f.check == "headings")


def test_edited_code_fence_and_snippet_include_are_reported() -> None:
    broken = TRANSLATED.replace('--8<-- "docs_src/tools/tutorial001.py"', "print('translated')")

    findings = validate_page("tools.md", ENGLISH, broken, GLOSSARY, script="latin")

    assert _checks(findings) == {"code"}
    messages = " ".join(f.message for f in findings)
    assert "content differs" in messages and "include lines" in messages


def test_changed_fence_info_string_is_reported() -> None:
    broken = TRANSLATED.replace("```python", "```py")

    findings = validate_page("tools.md", ENGLISH, broken, GLOSSARY, script="latin")

    assert any("info string is 'py', expected 'python'" in f.message for f in findings)


def test_unclosed_code_fence_is_reported() -> None:
    source = "# T {#t}\n\n```py\nprint(1)\n```\n\nTail prose.\n"
    unclosed = "# T {#t}\n\n```py\nprint(1)\n\nSchwanz prosa.\n"

    findings = validate_page("t.md", source, unclosed, GLOSSARY, script="latin")

    assert [(f.check, f.message) for f in findings] == [
        ("code", "code block 1 is not closed (add its closing fence marker)"),
    ]


def test_dropped_admonition_and_tab_and_table_changes_are_reported() -> None:
    broken = TRANSLATED.replace('!!! note "Naimung"', "Naimung:").replace("| naam | de tool naam |\n", "")

    findings = validate_page("tools.md", ENGLISH, broken, GLOSSARY, script="latin")

    assert _checks(findings) >= {"syntax", "tables"}


def test_tab_count_mismatch_is_reported() -> None:
    source = '=== "uv"\n\n    one\n\n=== "pip"\n\n    two\n'
    output = '=== "uv"\n\n    eins\n'

    findings = validate_page("t.md", source, output, GLOSSARY, script="latin")

    assert any(f.check == "syntax" and "content tabs" in f.message for f in findings)


def test_added_and_missing_links_are_reported() -> None:
    broken = TRANSLATED.replace("[Prompten](prompts.md)", "[Prompten](other.md) und [neu](extra.md)")

    findings = validate_page("tools.md", ENGLISH, broken, GLOSSARY, script="latin")

    messages = " ".join(f.message for f in findings if f.check == "links")
    assert "missing link targets ['prompts.md x1']" in messages
    assert "unexpected link targets ['extra.md x1', 'other.md x1']" in messages


def test_glossary_avoid_rendering_and_missing_keep_term_are_reported() -> None:
    glossary = Glossary(("MCP", "Context"), (Term("tool", "tuul", avoid=("werkzeug",), enforce=True),))
    broken = TRANSLATED.replace("MCP", "MZP").replace("de tool naam", "de werkzeug naam")

    findings = validate_page("tools.md", ENGLISH, broken, glossary, script="latin")

    messages = " ".join(f.message for f in findings if f.check == "glossary")
    assert "banned rendering 'werkzeug'" in messages
    assert "'MCP' must appear verbatim 1 time(s)" in messages


def test_unenforced_avoid_rendering_is_ignored() -> None:
    glossary = Glossary((), (Term("tool", "tuul", avoid=("naam",), enforce=False),))

    assert validate_page("tools.md", ENGLISH, TRANSLATED, glossary, script="latin") == []


def test_keep_terms_inside_code_do_not_count() -> None:
    source = "# T {#t}\n\nUse `Context` and Context.\n"
    output = "# T {#t}\n\nBenutze `Context` und Kontext.\n"

    findings = validate_page("t.md", source, output, GLOSSARY, script="latin")

    (finding,) = findings
    assert "'Context' must appear verbatim 1 time(s) as in the English block, found 0" in finding.message


def test_keep_term_plural_and_possessive_count_as_the_bare_term_on_both_sides() -> None:
    glossary = Glossary(("URI",), ())
    source = "# T {#t}\n\nMatch the URIs exactly. The URI's scheme is part of one URI.\n"
    # The language drops the English plural marker: three occurrences either way.
    dropped_plural = "# T {#t}\n\n精确匹配这些 URI。该 URI 的方案是一个 URI 的一部分。\n"

    assert validate_page("t.md", source, dropped_plural, glossary, script="cjk") == []


def test_dropped_keep_term_is_still_reported() -> None:
    glossary = Glossary(("URI",), ())
    source = "# T {#t}\n\nMatch the URIs exactly. The URI's scheme is part of one URI.\n"
    dropped_term = "# T {#t}\n\n精确匹配这些资源。该资源的方案是一个 URI 的一部分。\n"

    findings = validate_page("t.md", source, dropped_term, glossary, script="cjk")

    assert [f.message for f in findings if f.check == "glossary"] == [
        "'URI' must appear verbatim 3 time(s) as in the English block, found 1",
    ]


def test_placeholder_marker_is_reported() -> None:
    broken = TRANSLATED.replace("Xx `Context` objekt zint immer verfuegbar.", "[translation continues below]")

    findings = validate_page("tools.md", ENGLISH, broken, GLOSSARY, script="latin")

    assert any(f.check == "completeness" and "placeholder" in f.message for f in findings)


def test_abridgement_written_as_an_html_comment_is_reported() -> None:
    # Masking blanks HTML comments together with tags, so this placeholder is
    # read from the raw comments; an ordinary comment is not a placeholder.
    abridged = TRANSLATED.replace(
        "objekt zint immer verfuegbar.",
        "objekt zint immer verfuegbar. <!-- ok -->\n\n<!-- remaining sections omitted for brevity -->",
    )

    findings = validate_page("tools.md", ENGLISH, abridged, GLOSSARY, script="latin")

    quoted = "'<!-- remaining sections omitted for brevity -->'"
    assert [(f.check, f.message) for f in findings] == [
        ("completeness", f"placeholder text {quoted} — translate the whole block, never abridge")
    ]


def test_untranslated_english_section_fails_a_non_latin_target_even_when_the_block_is_all_latin() -> None:
    source = "# T {#t}\n\nIntro text.\n\n## Two {#two}\n\nSecond section text.\n"
    # The intro is translated; the second section was left entirely in English.
    output = f"# T {{#t}}\n\n这是已翻译的介绍段落。\n\n## Two {{#two}}\n\n{ENGLISH_RUN}\n"

    findings = validate_page("t.md", source, output, Glossary((), ()), script="cjk")

    assert [(f.block, f.check) for f in findings] == [(1, "completeness")]
    assert "untranslated English left in the text" in findings[0].message


def test_latin_script_target_is_never_scanned_for_english_runs() -> None:
    source = "# T {#t}\n\nIntro text.\n"
    output = f"# T {{#t}}\n\n{ENGLISH_RUN}\n"

    assert validate_page("t.md", source, output, Glossary((), ()), script="latin") == []


def test_front_matter_keys_must_match_and_only_title_may_be_translated() -> None:
    source = "---\ntitle: Tools\nweight: 2\n---\n\n# T {#t}\n"
    good = "---\ntitle: Tuulzen\nweight: 2\n---\n\n# T {#t}\n"
    bad = "---\ntitle: Tuulzen\nweight: 3\nextra: x\n---\n\n# T {#t}\n"

    assert validate_page("t.md", source, good, GLOSSARY, script="latin") == []
    findings = validate_page("t.md", source, bad, GLOSSARY, script="latin")
    assert findings and findings[0].check == "frontmatter"


def test_standalone_faithful_translation_has_no_findings() -> None:
    assert validate_page_standalone("tools.md", TRANSLATED) == []


def test_standalone_reports_unclosed_front_matter_a_missing_anchor_and_an_unclosed_fence() -> None:
    # The front matter never closes, so the whole page (title included) is body text.
    broken = "---\ntitle: Tuulzen\n\n# Tuulzen\n\n```python\nprint(1)\n\nSchwanz.\n"

    findings = validate_page_standalone("t.md", broken)

    assert {f.check for f in findings} == {"frontmatter", "headings", "code"}


def test_standalone_reports_malformed_and_reused_anchors_by_line() -> None:
    page = "# T {#t}\n\n## A {#same}\n\ntext\n\n## B {#same}\n\ntext\n\n## C {#bad!}\n\ntext\n"

    findings = validate_page_standalone("t.md", page)

    assert [f.message for f in findings if f.check == "headings"] == [
        "heading on line 7 reuses the anchor of line 3",
        "heading on line 11 anchor {#bad!} uses characters outside A-Za-z0-9_-",
    ]


def test_standalone_never_holds_a_page_to_the_glossary_or_the_source_it_was_not_made_from() -> None:
    # A banned rendering, a dropped keep-term and even a placeholder are what a
    # glossary edit or a stale source produce: outdated, never a `check` failure.
    page = "# T {#t}\n\nDas werkzeug ist da.\n\n[translation continues below]\n"

    assert validate_page_standalone("t.md", page) == []


NAV_LABELS = ["Get started", "The Context", "OAuth"]
NAV_GLOSSARY = Glossary(("Context", "OAuth"), (Term("started", "gestartet", avoid=("begonnen",), enforce=True),))


def _nav_findings(labels: dict[str, str], **options: bool) -> list[str]:
    return [str(f) for f in validate_nav_labels("nav.yml", NAV_LABELS, labels, NAV_GLOSSARY, **options)]


def test_faithful_nav_labels_have_no_findings() -> None:
    labels = {"Get started": "Los geht's", "The Context": "Der Context", "OAuth": "OAuth"}

    assert _nav_findings(labels) == []


def test_nav_label_key_set_must_match_exactly() -> None:
    labels = {"Get started": "Los geht's", "OAuth": "OAuth", "Stray": "Streuner"}

    findings = _nav_findings(labels)

    assert findings == [
        "nav.yml [labels] missing renderings for the labels ['The Context']",
        "nav.yml [labels] unexpected labels ['Stray'] (keep the English keys exactly)",
    ]
    # Offline check of an existing map: a label it lacks is untranslated, an extra one is stale.
    assert _nav_findings(labels, exact_keys=False) == []


def test_nav_label_findings_name_empty_value_dropped_keep_term_and_banned_rendering() -> None:
    labels = {"Get started": "gerade begonnen", "The Context": "Der Kontext", "OAuth": " "}

    findings = _nav_findings(labels)

    assert findings == [
        "nav.yml [glossary] banned rendering 'begonnen' of 'started' appears in 'Get started'",
        "nav.yml [glossary] 'Context' must appear verbatim 1 time(s) as in the label 'The Context', found 0",
        "nav.yml [labels] the rendering of 'OAuth' is empty",
    ]
