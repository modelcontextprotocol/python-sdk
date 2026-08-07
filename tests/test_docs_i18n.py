"""The documentation translation tool (`scripts/docs/translations.py`).

These are the SDK-defined guarantees of the pipeline: the parts of a page the
model must never change are re-imposed from the English, unchanged sections
survive re-translation byte-for-byte, a page failing its structural or
meaning gate is not published, and a language site is assembled from the
English tree with translations laid over it. The model is a fake driven by
scripted replies, so every test is offline and deterministic.
"""

import json
from pathlib import Path

import pytest
import translations as i18n
from inline_snapshot import snapshot

JAPANESE = i18n.Language(code="ja", name="日本語", theme_language="ja", hreflang="ja")
GLOSSARY = {
    "keep_in_source_language": ["MCP", "Python"],
    "terms": [{"source": "resource", "target": "リソース", "avoid": ["資源"], "enforce": True}],
}
INPUTS = i18n.Inputs(JAPANESE, "rules", "instructions", GLOSSARY, hash="inputs-v1")
MODELS = {"translate": "translator-model", "verify": "reviewer-model"}


class ScriptedModel(i18n.Model):
    """A `Model` that answers each call with the next scripted reply and records what it was asked."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[str] = []

    def complete(self, model: str, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        self.requests.append(messages[-1]["content"])
        return self.replies.pop(0)


ENGLISH = """\
# Tools {#tools}

A **tool** is a function the model behind any MCP client can call. See the [resource guide](resources.md).

## Your first tool {#your-first-tool}

```python
def add(a: int, b: int) -> int:
    return a + b
```

## Errors {#errors}

Raise to signal a failure.
"""


def test_headings_are_pinned_to_the_ids_the_english_site_renders():
    """SDK-defined: translated headings must carry the English page's slugs, so `#fragment` links resolve on every
    language site — a Japanese-only heading would otherwise slug to `_1`."""
    page = "# What's new in v2\n\n## The `_meta` field\n\n## Deploy & scale\n\n## Deploy & scale\n\n## インストール\n"
    assert i18n.heading_ids(page) == snapshot(
        ["whats-new-in-v2", "the-_meta-field", "deploy-scale", "deploy-scale_1", "_1"]
    )
    assert i18n.with_anchors(page).split("\n")[0] == snapshot("# What's new in v2 {#whats-new-in-v2}")


# A faithful Japanese translation of ENGLISH: prose translated, anchors, code and link targets untouched.
JAPANESE_PAGE = (
    ENGLISH.replace("# Tools {#tools}", "# ツール {#tools}")
    .replace(
        "A **tool** is a function the model behind any MCP client can call.",
        "**ツール** は MCP クライアントの背後にあるモデルが呼び出せる関数です。",
    )
    .replace("[resource guide]", "[リソースガイド]")
    .replace("## Your first tool {#your-first-tool}", "## 最初のツール {#your-first-tool}")
    .replace("## Errors {#errors}", "## エラー {#errors}")
    .replace("Raise to signal a failure.", "失敗を伝えるには例外を送出します。")
)


def test_a_faithful_translation_passes_the_structural_gate():
    """SDK-defined: a translation that keeps the page's shape, links, code and glossary rules has no findings."""
    assert i18n.structural_findings(ENGLISH, JAPANESE_PAGE, GLOSSARY) == []


def test_structural_gate_reports_each_broken_rule_as_a_repair_instruction():
    """SDK-defined: a dropped section, heading and link, a placeholder, a banned term and a lost keep-in-English
    term are each reported (the strings are fed back to the model as repair instructions)."""
    broken = """\
# ツール {#tools}

**tool** は資源です。[translation continues below]

## 最初のツール {#your-first-tool}

```python
def 足す(a, b):
    return a + b
```
"""
    assert i18n.structural_findings(ENGLISH, broken, GLOSSARY) == snapshot(
        [
            "the page must keep the same 3 `##` sections as the English, in the same order",
            "keep every heading, at the same level and in the same order as the English",
            "missing link targets ['resources.md'] — copy each one exactly from the English",
            "placeholder text '[translation continues below]' — translate the whole page, never abridge it",
            "banned rendering '資源' of 'resource' appears; use the glossary target",
            "'MCP' must appear verbatim, spelled exactly as in the English",
        ]
    )


def test_translation_repair_restores_anchors_code_and_strips_a_wrapping_fence():
    """SDK-defined: what the model must never change is re-imposed from the English rather than validated —
    the whole-page code fence models add is dropped, heading anchors come back, code bodies are copied over."""
    reply = JAPANESE_PAGE.replace(" {#tools}", "").replace("def add(a: int, b: int) -> int:", "def 加算(甲, 乙):")
    assert i18n.repair(ENGLISH, f"```markdown\n{reply}\n```\n") == JAPANESE_PAGE


def test_code_bodies_are_restored_even_when_an_earlier_fence_changed_length():
    """SDK-defined: each code fence gets the English body back regardless of how the model resized the bodies
    before it (splicing walks the fences from the last, so an edit never shifts the ones still to do)."""
    source = "# T {#t}\n\n```py\na = 1\nb = 2\n```\n\ntext\n\n```py\nc = 3\n```\n"
    reply = "# ティー\n\n```py\nα = 1\n```\n\nテキスト\n\n```py\nγ = 3\nδ = 4\n```\n"
    assert i18n.repair(source, reply) == snapshot(
        "# ティー {#t}\n\n```py\na = 1\nb = 2\n```\n\nテキスト\n\n```py\nc = 3\n```\n"
    )


def test_unchanged_sections_are_carried_over_from_the_previous_translation_verbatim():
    """SDK-defined: when only one `##` section of the English changed, the other sections keep the previous
    translation's exact bytes even though the model re-rendered them, so corrections stick between runs."""
    old_english = ENGLISH.replace("Raise to signal a failure.", "Return an error result.")
    previous = JAPANESE_PAGE.replace("失敗を伝えるには例外を送出します。", "エラーの結果を返します。").replace(
        "**ツール** は", "以前の翻訳: **ツール** は"
    )
    rephrased_everywhere = JAPANESE_PAGE.replace("**ツール** は", "モデルの気まぐれな言い換え: **ツール** は")
    model = ScriptedModel([rephrased_everywhere])

    text, problems = i18n.translate_page(
        ENGLISH, INPUTS, model, MODELS, previous=previous, old_hashes=i18n.block_hashes(old_english), verify=False
    )

    assert problems == []
    assert text == JAPANESE_PAGE.replace("**ツール** は", "以前の翻訳: **ツール** は")
    assert "only part of the English changed" in model.requests[0]
    assert "Changed sections:\n\n- ## Errors {#errors}\n" in model.requests[0]


def test_a_page_the_reviewer_still_flags_after_the_correction_round_is_not_published():
    """SDK-defined: the reviewer's blockers get one correction round; a blocker that survives fails the page.
    Findings whose quotes are not literal substrings of the texts are discarded as reviewer hallucination."""
    flipped = JAPANESE_PAGE.replace(
        "失敗を伝えるには例外を送出します。", "例外を送出してはいけません。失敗は無視されます。"
    )
    blocker = {
        "severity": "blocker",
        "source_quote": "Raise to signal a failure.",
        "target_quote": "例外を送出してはいけません。失敗は無視されます。",
        "explanation": "the instruction is inverted",
    }
    hallucination = {**blocker, "target_quote": "words the translation never contained"}
    model = ScriptedModel([flipped, json.dumps([blocker, hallucination]), flipped, json.dumps([blocker])])

    text, problems = i18n.translate_page(ENGLISH, INPUTS, model, MODELS)

    assert text is None
    assert problems == snapshot(
        [
            'meaning: "Raise to signal a failure." -> "例外を送出してはいけません。失敗は無視されます。": '
            "the instruction is inverted"
        ]
    )
    assert "A bilingual reviewer found places" in model.requests[2]
    # only the real blocker is relayed to the model; the hallucinated finding was discarded
    assert "words the translation never contained" not in model.requests[2]


def write(path: Path, text: str) -> None:
    """Write a repo file the way the tool reads it: UTF-8 with `\\n` line endings, on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


@pytest.fixture
def docs_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository tree with two English pages, one Japanese translation and the ja UI strings."""
    write(tmp_path / "docs" / "index.md", "# Home\n\nSee [tools](tools.md) and the [API](api/mcp/index.md).\n")
    write(tmp_path / "docs" / "tools.md", "# Tools\n\nEnglish body.\n")
    write(tmp_path / "docs" / "translations.md", "# Translations\n")
    write(
        tmp_path / "mkdocs.yml",
        "site_url: https://docs.example/\nnav:\n  - Home: index.md\n  - Tools: tools.md\n"
        "  - Translations: translations.md\n  - API Reference: api/\n",
    )
    write(
        tmp_path / "i18n" / "languages.yml",
        "languages:\n  - {code: ja, name: 日本語}\nexclude_pages: [translations.md]\n"
        "models: {translate: t, verify: v}\nbanners:\n  disclosure: 'MT: [English]({english_url})'\n"
        "  outdated: 'behind'\n  untranslated: 'English shown, see [how]({translations_url})'\n",
    )
    write(tmp_path / "i18n" / "general-prompt.md", "rules")
    write(tmp_path / "i18n" / "ja" / "instructions.md", "instructions")
    write(tmp_path / "i18n" / "ja" / "glossary.json", json.dumps(GLOSSARY))
    write(
        tmp_path / "i18n" / "ja" / "pages" / "index.md",
        "# ホーム {#home}\n\n[ツール](tools.md) と [API](api/mcp/index.md) を参照。\n",
    )
    for name, path in (("ROOT", tmp_path), ("DOCS", tmp_path / "docs"), ("I18N", tmp_path / "i18n")):
        monkeypatch.setattr(i18n, name, path)
    inputs = i18n.load_inputs(JAPANESE)
    page_record = {
        "source_hash": i18n.sha256(i18n.read_page(tmp_path / "docs", "index.md")),
        "block_hashes": i18n.block_hashes(i18n.with_anchors(i18n.read_page(tmp_path / "docs", "index.md"))),
        "inputs_hash": inputs.hash,
        "model": "t",
        "translated_at": "now",
    }
    ui = {
        "strings": {"Home": "ホーム", "@banner:disclosure": "機械翻訳: [英語版]({english_url})"},
        "source_hash": "old",
        "inputs_hash": inputs.hash,
        "model": "t",
        "translated_at": "now",
    }
    write(tmp_path / "i18n" / "ja" / "state.json", json.dumps({"pages": {"index.md": page_record}, "ui": ui}))
    return tmp_path


def test_stage_overlays_translations_and_serves_english_with_a_notice_for_the_rest(docs_repo: Path):
    """SDK-defined: the ja site is the English tree with translated pages laid over it — a translation gets the
    (translated) disclosure notice and its API links pointed at the English reference; untranslated and
    excluded pages are served in English with the not-translated notice."""
    staged = i18n.stage(JAPANESE, "https://docs.example", i18n.load_registry())

    assert i18n.read_page(staged, "index.md") == snapshot(
        "# ホーム {#home}\n\n機械翻訳: [英語版](https://docs.example/)\n\n"
        "[ツール](tools.md) と [API](https://docs.example/api/mcp/) を参照。\n"
    )
    assert i18n.read_page(staged, "tools.md") == snapshot(
        "# Tools\n\nEnglish shown, see [how](translations.md)\n\nEnglish body.\n"
    )
    assert i18n.read_page(staged, "translations.md") == snapshot(
        "# Translations\n\nEnglish shown, see [how](translations.md)\n"
    )


def test_an_outdated_translation_is_only_served_while_its_links_and_anchors_still_match_the_english(
    docs_repo: Path,
) -> None:
    """SDK-defined: an outdated translation that would break the strict build (a link the English tree no longer
    has, or an English anchor its headings no longer carry) is withdrawn until the next translate run."""
    universe = {"index.md": ["home"], "tools.md": ["tools"], "translations.md": ["translations"]}
    translated = i18n.read_page(i18n.I18N / "ja" / "pages", "index.md")
    assert i18n.servable(translated, "index.md", universe)
    assert not i18n.servable(translated.replace("tools.md", "tools-old.md"), "index.md", universe)
    assert not i18n.servable(translated.replace("{#home}", "{#casa}"), "index.md", universe)


def test_status_marks_pages_current_outdated_and_missing_from_content_and_input_hashes(
    docs_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SDK-defined: a page is current only while both the English text and the prompt inputs it was translated from
    are unchanged; editing the English makes it outdated, and a page with no translation is missing."""
    write(docs_repo / "docs" / "index.md", "# Home\n\nThe English changed since translation.\n")

    exit_code = i18n.command_status(i18n.load_registry(), None)

    assert exit_code == 0
    assert capsys.readouterr().out == snapshot(
        "ja (日本語): 1 missing, 1 outdated, 0 current; UI strings outdated\n"
        "  outdated  index.md\n  missing   tools.md\n"
    )


def test_ui_strings_keep_prior_renderings_and_reject_replies_that_lose_a_placeholder(docs_repo: Path):
    """SDK-defined: the sidebar labels and banners are translated as one JSON map; a still-valid prior rendering
    is kept verbatim, and a reply that drops a banner placeholder (or unbalances a brace) is sent back to be
    fixed — the banner is a `str.format` template at staging, so a mismatch would break the site build."""
    strings = i18n.ui_strings(i18n.load_registry())
    broken = json.dumps({**strings, "Tools": "ツール", "@banner:disclosure": "機械翻訳です。} を参照"})
    fixed = json.dumps({**strings, "Tools": "ツール", "@banner:disclosure": "機械翻訳: [英語版]({english_url})"})
    model = ScriptedModel([broken, fixed])

    translated = i18n.translate_ui(strings, INPUTS, model, MODELS, keep={"Home": "ホーム"})

    assert translated == snapshot(
        {
            "Home": "ホーム",
            "Tools": "ツール",
            "Translations": "Translations",
            "API Reference": "API Reference",
            "@banner:disclosure": "機械翻訳: [英語版]({english_url})",
            "@banner:outdated": "behind",
            "@banner:untranslated": "English shown, see [how]({translations_url})",
        }
    )
    assert "keep exactly the placeholders ['{english_url}'] and no other braces" in model.requests[1]


def test_a_prior_ui_rendering_is_kept_only_while_its_english_and_the_inputs_are_unchanged(docs_repo: Path):
    """SDK-defined: rewording a banner's English (or editing the language inputs) drops its prior rendering so
    the change actually reaches the translated sites; untouched strings keep theirs verbatim."""
    strings = i18n.ui_strings(i18n.load_registry())
    old_source = {**strings, "@banner:outdated": "the English wording it was translated from"}
    ui = {"strings": {"Home": "ホーム", "@banner:outdated": "古い訳"}, "source": old_source}

    assert i18n.kept_ui(strings, {"ui": {**ui, "inputs_hash": INPUTS.hash}}, INPUTS) == {"Home": "ホーム"}
    assert i18n.kept_ui(strings, {"ui": {**ui, "inputs_hash": "stale"}}, INPUTS) == {}


def test_removing_a_section_from_the_english_is_not_short_circuited_as_unchanged():
    """SDK-defined: when English `##` sections are deleted (or reordered) rather than edited, the page is still
    sent to the model — every remaining section is 'unchanged', but the stale ones must go."""
    previous = JAPANESE_PAGE
    source = ENGLISH.rsplit("\n\n## Errors", 1)[0] + "\n"  # the last section is removed from the English
    model = ScriptedModel([JAPANESE_PAGE.rsplit("\n\n## エラー", 1)[0] + "\n"])

    text, problems = i18n.translate_page(
        source, INPUTS, model, MODELS, previous=previous, old_hashes=i18n.block_hashes(ENGLISH), verify=False
    )

    assert problems == []
    assert text == JAPANESE_PAGE.rsplit("\n\n## エラー", 1)[0] + "\n"
    assert "sections were removed or reordered" in model.requests[0]


def test_a_page_whose_headings_stayed_english_is_sent_back():
    """SDK-defined: when most of a page's prose headings are still the English text, the gate asks the model to
    translate them (keeping their anchors) — code-only and keep-in-English headings do not count."""
    output = ENGLISH.replace("# Tools", "# ツール")  # only the H1 translated; both `##` headings left English
    assert i18n.structural_findings(ENGLISH, output, GLOSSARY) == snapshot(
        [
            "these headings are still English — translate their text, keeping the anchors:"
            " ['Your first tool', 'Errors']",
        ]
    )
