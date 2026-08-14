"""The documentation translation tool (`scripts/docs/translations.py`).

Everything here is tool-defined behaviour: what the model must never change is
re-imposed from the English page (or, for links, checked against it), unchanged
sections survive re-translation byte for byte, a page's state lives in its own
front matter, and a language site is the English tree with translations laid
over it and a notice on every page. The model is a scripted fake and the
repository a `tmp_path` tree, so every test is offline and deterministic.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import translations as t
from inline_snapshot import snapshot

MKDOCS = """\
site_name: Test docs
nav:
  - Home: index.md
  - Tools: tools.md
  - Translations: translations.md
  - Migration: migration.md
  - API Reference: api/
markdown_extensions:
  - admonition
  - attr_list
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.snippets:
      check_paths: true
"""

LANGUAGES = """\
model: test-model
exclude: [migration.md]
languages:
  - code: ja
    name: 日本語
    theme: ja
    hreflang: ja
"""

NOTICES = """\
# Notices

## Machine translation {#translated}

Machine translated; the [English page](ENGLISH_PAGE) is authoritative. See [Translations](TRANSLATIONS_PAGE).

## Translation behind the English page {#outdated}

Parts may be out of date; compare the [English page](ENGLISH_PAGE).

## Shown in English {#english}

Not translated yet; [Translations](TRANSLATIONS_PAGE) explains why.
"""

NOTICES_JA = """\
# お知らせ

## 機械翻訳 {#translated}

機械翻訳です。正式版は[英語版](ENGLISH_PAGE)です。[翻訳について](TRANSLATIONS_PAGE)を参照。

## 英語版より古い翻訳 {#outdated}

一部が古い可能性があります。[英語版](ENGLISH_PAGE)と比べてください。

## 英語で表示 {#english}

未翻訳です。理由は[翻訳について](TRANSLATIONS_PAGE)を参照。
"""

GLOSSARY = {
    "keep": ["MCP", "Python"],
    "terms": [
        {"source": "tool", "target": "ツール", "avoid": ["道具"]},
        {"source": "server", "target": "サーバー", "note": "Katakana, long vowel kept."},
    ],
}

INDEX = """\
# Home

Welcome to MCP. Read about [tools](tools.md#errors) or the [API](api/mcp/index.md).

## Install

Run `pip install mcp`, then read the [Python](https://www.python.org/) docs.
"""

TOOLS = """\
# Tools

A **tool** is a function the model can call; start at [home](index.md#install).

## Your first tool

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "Heads up"
    Every tool is `async` friendly.

## Errors

Raise to signal a failure.
"""

# English front matter (even with a `#` comment line in it) is dropped wherever the page is read.
TRANSLATIONS = (
    "---\ndescription: About the translated sites.\n# not a heading\n---\n# Translations\n\nHow this works.\n"
)

# Faithful model replies: prose translated, code, link targets and markers untouched, no `{#id}` pins.
INDEX_JA = """\
# ホーム

MCP へようこそ。[ツール](tools.md#errors)または [API](api/mcp/index.md) を参照してください。

## インストール

`pip install mcp` を実行し、[Python](https://www.python.org/) のドキュメントを読みます。
"""

TRANSLATIONS_JA = "# 翻訳について\n\n仕組みの説明です。\n"

TOOLS_JA = """\
# ツール

**ツール**はモデルが呼び出せる関数です。[ホーム](index.md#install)から始めましょう。

## 最初のツール

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "注意"
    どのツールも `async` に対応しています。

## エラー

失敗を伝えるには例外を送出します。
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make_repo(tmp_path: Path) -> Path:
    """A repository with three English prose pages, an excluded page and the ja inputs, nothing translated."""
    root = tmp_path / "repo"
    write(root / "mkdocs.yml", MKDOCS)
    write(root / "docs" / "index.md", INDEX)
    write(root / "docs" / "tools.md", TOOLS)
    write(root / "docs" / "translations.md", TRANSLATIONS)
    write(root / "docs" / "migration.md", "# Migration\n\nSee [errors](tools.md#errors).\n")
    write(root / "docs" / "img" / "logo.svg", "<svg/>\n")
    write(root / "docs_src" / "server.py", "print('hi')\n")
    write(root / "i18n" / "languages.yml", LANGUAGES)
    write(root / "i18n" / "general-prompt.md", "General rules.\n")
    write(root / "i18n" / "notices.md", NOTICES)
    write(root / "i18n" / "ja" / "instructions.md", "Japanese rules.\n")
    write(root / "i18n" / "ja" / "glossary.json", json.dumps(GLOSSARY, ensure_ascii=False))
    return root


class FakeTranslator:
    """Answers each call with the next scripted reply (raising it if it is an exception) and records the calls."""

    def __init__(self, replies: Sequence[str | t.Completion | Exception]) -> None:
        self.replies = list(replies)
        self.models: list[str] = []
        self.systems: list[str] = []
        self.conversations: list[list[t.Message]] = []

    def complete(self, *, model: str, system: str, messages: Sequence[t.Message], max_tokens: int) -> t.Completion:
        self.models.append(model)
        self.systems.append(system)
        self.conversations.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, t.Completion) else t.Completion(reply, t.Usage(1000, 400, 900, 100))


def run(
    capsys: pytest.CaptureFixture[str], root: Path, *argv: str, translator: t.Translator | None = None
) -> tuple[int, str, str]:
    code = t.main(list(argv), root=root, translator=translator)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def translate_all(capsys: pytest.CaptureFixture[str], root: Path) -> None:
    """Publish faithful translations of the three pages and the notices through the real command."""
    fake = FakeTranslator([INDEX_JA, TOOLS_JA, TRANSLATIONS_JA, NOTICES_JA])
    assert run(capsys, root, "translate", "--lang", "ja", translator=fake)[0] == 0


def test_sections_tile_the_page_and_blank_lines_belong_to_the_heading_after_them() -> None:
    """Tool-defined: a page splits into intro + one string per `##` (a `##` inside a fence is code), the parts
    join back to the page, and appending a section leaves every earlier section's hash unchanged."""
    page = "# Title\n\nIntro.\n\n\n## One\n\n```md\n## not a heading\n```\n\n## Two\n\nEnd.\n"

    assert t.sections(page) == snapshot(
        [
            """\
# Title

Intro.
""",
            """\


## One

```md
## not a heading
```
""",
            """\

## Two

End.
""",
        ]
    )
    assert "".join(t.sections(page)) == page
    assert t.section_hashes(page + "\n## Three\n\nMore.\n")[:3] == t.section_hashes(page)


def test_provenance_front_matter_round_trips_and_keeps_all_digit_hashes_as_strings() -> None:
    """Tool-defined: the generated file is front matter + body; a hash of digits only must not come back as
    a number, and a block from another tool version or without the record reads as no provenance at all."""
    hashes = ("1234567890123456", "00ff00ff00ff00ff")
    text = t.with_provenance("# 本文\n", hashes)

    assert text == snapshot("""\
---
translation:
  sections: ['1234567890123456', 00ff00ff00ff00ff]
  tool: 1
---
# 本文
""")
    front_matter, body = t.split_front_matter(text)
    assert (t.read_provenance(front_matter), body) == (hashes, "# 本文\n")
    assert t.read_provenance("translation: {sections: [], tool: 99}\n") is None
    assert t.read_provenance("title: Just a page\n") is None


def test_heading_ids_are_the_ones_the_site_renderer_produces(tmp_path: Path) -> None:
    """Tool-defined: ids come from the real markdown stack (dedupe suffixes, punctuation, `__init__`, explicit
    ids, inline code, no space after `##`), and pinning them in escaped source form renders the same ids."""
    repo = t.load_repo(make_repo(tmp_path))
    page = (
        "# What's new?\n\n## Step\n\n## Step\n\n## The `__init__` hook\n\n## Custom {#my-id}\n\n"
        "##Glued\n\n## Über `Config.load()` & friends!\n\n## 日本語\n"
    )

    ids = repo.heading_ids(page)

    assert ids == snapshot(
        ["whats-new", "step", "step_1", "the-__init__-hook", "my-id", "glued", "uber-configload-friends", "_1"]
    )
    pinned = t.reimpose(page, ids, page)
    assert isinstance(pinned, str)
    assert pinned.split("\n")[6] == snapshot("## The `__init__` hook {#the-\\_\\_init\\_\\_-hook}")
    assert repo.heading_ids(pinned) == ids


def test_heading_the_source_scan_cannot_pin_makes_the_page_an_error(tmp_path: Path) -> None:
    """Tool-defined: a setext heading renders but is not an ATX heading at column 0, so ids cannot be paired
    positionally; the page is refused rather than mis-pinned."""
    repo = t.load_repo(make_repo(tmp_path))

    with pytest.raises(t.PageError) as excinfo:
        repo.heading_ids("# Title\n\nSetext\n------\n")

    assert str(excinfo.value) == snapshot("the page renders 2 headings but 1 are ATX headings at column 0")


def test_many_attribute_blocks_pin_the_last_id_only_when_they_end_the_heading() -> None:
    """Tool-defined: a run of `{...}` blocks ending the line pins the last block's id, in either attr_list
    spelling; with text after it the run stays heading text and pins nothing, and the scan still returns
    promptly however many blocks (colon-led ones too) it has."""
    blocks, colons = "{ a } " * 20, "{: #a}" * 20
    page = f"## Pinned {blocks}{{#last}}\n## Prose {blocks}end\n## Colons {colons} tail\n## A {{:#a}}\n## B {{: #a }}\n"

    assert t.parse_headings(page) == [
        t.Heading(0, 2, "Pinned", "last"),
        t.Heading(1, 2, f"Prose {blocks}end", None),
        t.Heading(2, 2, f"Colons {colons} tail", None),
        t.Heading(3, 2, "A", "a"),
        t.Heading(4, 2, "B", "a"),
    ]


ENGLISH = """\
# Guide

See [tools](tools.md#errors), the [spec](https://spec.example/) and ![logo](img/logo.svg).

## The `__init__` hook

```python title="app.py" hl_lines="1"
--8<-- "docs_src/server.py"
def main(): ...  # (1)!
```

## Step

## Step
"""


def test_reimpose_restores_fences_pins_ids_and_leaves_reordered_links_where_the_translation_put_them() -> None:
    """Tool-defined: the wrapper fence is dropped, each fence comes back opener-through-closer, ids are pinned
    positionally in escaped form (a `{#...}` glued to CJK text, or doubled, is replaced), and links the
    translation reordered within a section keep their own targets: nothing is moved back by position."""
    reply = (
        "```markdown\n# ガイド\n\n![ロゴ](img/logo.svg)、[仕様](https://spec.example/)、[ツール](tools.md#errors)。\n\n"
        "## `__init__` フック{#init}\n\n```py\ndef メイン(): ...\n```\n\n## 手順\n\n## 手順 {#wrong} {: #twice }\n```"
    )

    result = t.reimpose(ENGLISH, ["guide", "the-__init__-hook", "step", "step_1"], t.unwrap(ENGLISH, reply))

    assert result == snapshot("""\
# ガイド {#guide}

![ロゴ](img/logo.svg)、[仕様](https://spec.example/)、[ツール](tools.md#errors)。

## `__init__` フック {#the-\\_\\_init\\_\\_-hook}

```python title="app.py" hl_lines="1"
--8<-- "docs_src/server.py"
def main(): ...  # (1)!
```

## 手順 {#step}

## 手順 {#step_1}
""")


def test_unwrap_ends_the_reply_with_exactly_the_trailing_newlines_of_the_english() -> None:
    """Tool-defined: a reply with newlines to spare, or none, is stored ending the way its English page ends,
    so the last section's bytes do not depend on how the model happened to close its reply."""
    assert t.unwrap("# Title\n", "```markdown\n# タイトル\n```\n\n\n") == "# タイトル\n"
    assert t.unwrap("# Title\n", "# タイトル\n\n") == "# タイトル\n"
    assert t.unwrap("# Title\n", "# タイトル") == "# タイトル\n"


@pytest.mark.parametrize(
    ("reply", "findings"),
    [
        pytest.param(
            ENGLISH.replace("## Step\n\n## Step\n", "## Step\n"),
            snapshot(["3 headings vs 4 in the English: keep every heading, and no others"]),
            id="heading-dropped",
        ),
        pytest.param(
            ENGLISH.replace("## Step\n\n", "### Step\n\n"),
            snapshot(["`Step` is a level-3 heading but `Step` is level 2"]),
            id="heading-level",
        ),
        pytest.param(
            ENGLISH.replace('hl_lines="1"\n', 'hl_lines="1"\n```\n\n```text\n'),
            snapshot(["## The `__init__` hook: 2 code fences vs 1 in the English: keep each where it is, add none"]),
            id="fence-added",
        ),
        pytest.param(
            ENGLISH.replace("## Step\n\n## Step\n", "## Step\n\n```python\npass\n```\n\n## Step\n").replace(
                '```python title="app.py" hl_lines="1"\n--8<-- "docs_src/server.py"\ndef main(): ...  # (1)!\n```\n', ""
            ),
            snapshot(
                [
                    "## The `__init__` hook: 0 code fences vs 1 in the English: keep each where it is, add none",
                    "## Step: 1 code fences vs 0 in the English: keep each where it is, add none",
                ]
            ),
            id="fence-moved-to-another-section",
        ),
        pytest.param(
            ENGLISH.replace("\n```\n\n## Step", "\n\n## Step"),
            snapshot(
                [
                    "the code fence opened on line 7 is never closed",
                    "2 headings vs 4 in the English: keep every heading, and no others",
                ]
            ),
            id="fence-unclosed",
        ),
        pytest.param(
            ENGLISH.replace("tools.md#errors", "tools.md#エラー"),
            snapshot(
                [
                    "missing links to ['tools.md#errors']: keep every link of the English where it is",
                    "unexpected links to ['tools.md#エラー']: add no links of your own",
                ]
            ),
            id="target-mangled",
        ),
        pytest.param(
            ENGLISH.replace("See [tools](tools.md#errors), the", "See the").replace(
                "## Step\n\n## Step\n", "## Step\n\nSee [tools](tools.md#errors).\n\n## Step\n"
            ),
            snapshot(
                [
                    "missing links to ['tools.md#errors']: keep every link of the English where it is",
                    "unexpected links to ['tools.md#errors']: add no links of your own",
                ]
            ),
            id="link-moved-to-another-section",
        ),
    ],
)
def test_reimpose_names_each_structural_mismatch(reply: str, findings: list[str]) -> None:
    """Tool-defined: a heading count or level the reply gets wrong, or a section's fence count (so a code
    block moved under another `##` counts twice), cannot be repaired positionally, and a link target its
    English section lacks (mangled, or moved across sections) is never rewritten, so each becomes a finding
    for the repair turn."""
    result = t.reimpose(ENGLISH, ["guide", "the-__init__-hook", "step", "step_1"], reply)

    assert result == t.Mismatch(findings)


def test_validate_flags_code_spans_markers_banned_terms_and_abridgement() -> None:
    """Tool-defined: what re-imposition cannot fix is reported for the repair turn; a banned rendering
    inside code is not prose, and a link label or anything the English itself says is not an abridgement."""
    glossary = t.Glossary(("MCP",), (t.Term("tool", "ツール", "", ("道具",)),))
    english = '# T\n\nUse `ctx` and `run()`. See [Translations](t.md), not [...].\n\n!!! tip "Hint"\n    A table.\n'
    faithful = (
        "# T\n\n`ctx` と `run()` を使います。`道具` はコード。[Translations](t.md) 参照、[...] 以外。\n\n"
        '!!! tip "ヒント"\n    表。\n'
    )
    broken = (
        "# T\n\n`ctx` と `run` を使う道具です。[translation continues below]\n\n"
        '!!! note "ヒント"\n    <!-- rest of the table omitted -->\n'
    )

    assert t.validate(english, english, glossary) == []
    assert t.validate(english, faithful.replace("`道具` はコード。", ""), glossary) == []
    assert t.validate(english, faithful, glossary) == snapshot(
        ["unexpected inline code ['道具']: use only the English `code spans`"]
    )
    assert t.validate(english, broken, glossary) == snapshot(
        [
            "missing inline code ['run()']: copy every `code span` of the English",
            "unexpected inline code ['run']: use only the English `code spans`",
            "block markers ['!!! note'] vs ['!!! tip'] in the English: keep each `!!!`/`???`/`===` line and its type",
            "banned rendering '道具' of 'tool' appears: use 'ツール'",
            "placeholder '<!-- rest of the table omitted -->': translate the whole page, never abridge it",
            "placeholder '[translation continues below]': translate the whole page, never abridge it",
        ]
    )


LISTED = """\
# Translations

How this works:

- one
- two
    1. nested
* three

| Note | Meaning |
|------|---------|
| a | b |
| c | d |

```text
- not an item
| not | a row |
```
"""

LISTED_JA = """\
# 翻訳について

仕組みの説明です。

- いち
- に
    1. 入れ子
* さん

| お知らせ | 意味 |
|------|---------|
| a | b |
| c | d |

```text
- not an item
| not | a row |
```
"""


def test_validate_counts_list_items_and_table_rows_whatever_the_language_of_a_placeholder() -> None:
    """Tool-defined: a reply that drops list items (at any depth, any bullet) or table rows is a finding
    naming the part of the page, even when the note it leaves in their place is not English; lines inside
    fenced code do not count."""
    glossary = t.Glossary((), ())
    shortened = LISTED_JA.replace("    1. 入れ子\n* さん\n", "（以下同様）\n").replace("| c | d |\n", "")

    assert t.block_counts(LISTED) == {"list items": 4, "table rows": 4}
    assert t.validate(LISTED, LISTED_JA, glossary) == []
    assert t.validate(LISTED, shortened, glossary, "## Some section") == snapshot(
        [
            "## Some section: 2 list items vs 4 in the English: translate them one for one, dropping none",
            "## Some section: 3 table rows vs 4 in the English: translate them one for one, dropping none",
        ]
    )


@pytest.mark.parametrize(
    ("glossary", "message"),
    [
        pytest.param({"keep": [], "terms": [{"source": "a", "target": "b", "enforce": True}]}, "TypeError(", id="key"),
        pytest.param({"keep": [], "terms": ["tool"]}, "ValueError(", id="entry-string"),
        pytest.param({"keep": "MCP", "terms": []}, "`keep` must be a list of strings\n", id="keep-string"),
        pytest.param(
            {"keep": [], "terms": [{"source": "host", "target": "Host", "avoid": "Gastgeber"}]},
            "`terms` entry {'source': 'host', 'target': 'Host', 'avoid': 'Gastgeber'} needs string"
            " `source`/`target`/`note` and a list `avoid`\n",
            id="avoid-string",
        ),
    ],
)
def test_glossary_of_the_wrong_shape_stops_translate_with_exit_2_but_never_breaks_stage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], glossary: dict[str, object], message: str
) -> None:
    """Tool-defined: a glossary entry with a key `Term` lacks, an entry that is no object, or a bare string
    where a list belongs, stops the command that prompts with it (exit 2, naming the file and the field) before
    any page work; the site build's `stage` never reads prompt inputs, so a broken one cannot fail a build."""
    root = make_repo(tmp_path)
    path = root / "i18n" / "ja" / "glossary.json"
    write(path, json.dumps(glossary))

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=FakeTranslator([]))

    assert (code, out) == (2, "")
    assert err.startswith(f"translations: {path}: {message}")  # an exception's own text is the interpreter's
    assert run(capsys, root, "stage", "--lang", "ja") == (0, "staged ja at .build/i18n/ja/docs\n", "")


def test_translate_writes_pages_with_provenance_and_a_second_run_makes_no_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: missing pages are translated whole and written with pinned ids and provenance front
    matter; once every page is current a run selects nothing and never builds a client."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([INDEX_JA, TOOLS_JA, TRANSLATIONS_JA, NOTICES_JA])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, err) == (0, "")
    assert out == snapshot("""\
translated: index.md (2 of 2 sections)
translated: tools.md (3 of 3 sections)
translated: translations.md (1 of 1 sections)
translated: i18n/notices.md (4 of 4 sections)
usage: 4000 input / 1600 output / 3600 cache-write / 400 cache-read tokens
""")
    assert (root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8") == snapshot("""\
---
translation:
  sections: [66b1e7a79f363f39, 0c72bd9638620faf, 21db181e57737c09]
  tool: 1
---
# ツール {#tools}

**ツール**はモデルが呼び出せる関数です。[ホーム](index.md#install)から始めましょう。

## 最初のツール {#your-first-tool}

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "注意"
    どのツールも `async` に対応しています。

## エラー {#errors}

失敗を伝えるには例外を送出します。
""")
    assert fake.conversations[1] == [t.Message("user", t.translate_request(TOOLS))]
    assert fake.systems[0] == snapshot("""\
General rules.

# Target language: 日本語 (`ja`)

Japanese rules.

## Glossary

These terms always stay in English, spelled exactly like this:

- MCP
- Python

Use these renderings; the notes are binding:

- tool → ツール (never: 道具)
- server → サーバー. Katakana, long vowel kept.\
""")

    code, out, err = run(capsys, root, "translate", "--lang", "ja")

    assert (code, out, err) == (0, "ja: nothing to translate\n", "")
    assert run(capsys, root, "status") == snapshot(
        (0, "ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable\n", "")
    )


def test_docs_translate_model_overrides_the_registry_model_for_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool-defined: calls use the registry's model unless `DOCS_TRANSLATE_MODEL` names another one to
    trial, and neither is ever written into the generated page."""
    root = make_repo(tmp_path)
    monkeypatch.delenv("DOCS_TRANSLATE_MODEL", raising=False)
    fake = FakeTranslator([INDEX_JA, INDEX_JA])
    assert run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", translator=fake)[0] == 0
    monkeypatch.setenv("DOCS_TRANSLATE_MODEL", "trial-model")

    code, _, _ = run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", translator=fake)

    assert (code, fake.models) == (0, ["test-model", "trial-model"])
    assert "model" not in (root / "i18n" / "ja" / "pages" / "index.md").read_text(encoding="utf-8")


def test_translate_pages_retranslates_the_named_pages_from_scratch_even_when_a_translation_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: `--pages` sends exactly the request a missing page gets (the English alone, no previous
    translation to anchor on) although the page is current, publishes the result with provenance, and a page
    outside the nav is exit 2."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    fake = FakeTranslator([INDEX_JA.replace("へようこそ", "へようこそ！")])

    code, out, _ = run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", translator=fake)

    assert (code, out.split("\n")[0]) == (0, "translated: index.md (2 of 2 sections)")
    assert fake.conversations[0] == [t.Message("user", t.translate_request(INDEX))]
    assert "MCP へようこそ！" in (root / "i18n" / "ja" / "pages" / "index.md").read_text(encoding="utf-8")
    assert run(capsys, root, "status")[1] == snapshot("ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable\n")

    code, _, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "nope.md", translator=fake)

    assert (code, err) == snapshot(
        (2, "translations: not translatable pages (nav paths such as servers/tools.md): ['nope.md']\n")
    )


def test_outdated_page_retranslates_the_changed_section_and_carries_the_rest_forward(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: editing one English section marks the page outdated; the prompt carries the previous
    translation and names that section for retranslation, and every other section keeps its previous bytes
    even though the model re-rendered them."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    write(root / "docs" / "tools.md", TOOLS.replace("Raise to signal a failure.", "Raise `ToolError` to fail."))
    reply = TOOLS_JA.replace("**ツール**は", "気まぐれな言い換え：**ツール**は").replace(
        "失敗を伝えるには例外を送出します。", "失敗するには `ToolError` を送出します。"
    )
    fake = FakeTranslator([reply])

    code, out, _ = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, out.split("\n")[0]) == (0, "translated: tools.md (1 of 3 sections)")
    assert fake.conversations[0][0].content == snapshot("""\
This page was translated before. Retranslate it: translate the sections listed below
afresh from the current English, applying the current language instructions and glossary
(their previous wording may be outdated); everywhere else, reproduce the previous
translation line by line, changing nothing. Keep the retranslated sections consistent in
terminology and tone with their surroundings. A section is the introduction before the
first `##` heading, or one `##` heading with everything under it.

Sections to retranslate:

- ## Errors

Current English page:

<english-page>
# Tools

A **tool** is a function the model can call; start at [home](index.md#install).

## Your first tool

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "Heads up"
    Every tool is `async` friendly.

## Errors

Raise `ToolError` to fail.

</english-page>

Previous translation of the page:

<previous-translation>
# ツール {#tools}

**ツール**はモデルが呼び出せる関数です。[ホーム](index.md#install)から始めましょう。

## 最初のツール {#your-first-tool}

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "注意"
    どのツールも `async` に対応しています。

## エラー {#errors}

失敗を伝えるには例外を送出します。

</previous-translation>

Return only the full translated page.\
""")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    assert "気まぐれ" not in body
    assert body.endswith("## エラー {#errors}\n\n失敗するには `ToolError` を送出します。\n")


def test_banned_rendering_is_a_finding_in_a_retranslated_section_but_not_in_a_carried_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: validation reads the page as it will be written, and only the sections this run rewrites.
    A carried section using a word the glossary has since banned is published text (`--pages` redoes it), so
    it is neither a finding nor touched; the same word in the retranslated section is repaired as ever."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    banned = {"source": "function", "target": "ファンクション", "avoid": ["関数"]}  # the published intro says 関数
    write(root / "i18n" / "ja" / "glossary.json", json.dumps({**GLOSSARY, "terms": [*GLOSSARY["terms"], banned]}))
    write(root / "docs" / "tools.md", TOOLS.replace("Raise to signal a failure.", "Raise from the function."))
    slipped = TOOLS_JA.replace("失敗を伝えるには例外を送出します。", "関数から送出します。")
    repaired = TOOLS_JA.replace("失敗を伝えるには例外を送出します。", "ファンクションから送出します。")
    fake = FakeTranslator([slipped, repaired])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, err, fake.replies, out.split("\n")[0]) == (0, "", [], "translated: tools.md (1 of 3 sections)")
    assert fake.conversations[1][2].content == snapshot("""\
Your translation broke the following structural rules. Fix each problem and return the
full corrected page, changing nothing else:

- banned rendering '関数' of 'function' appears: use 'ファンクション'\
""")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    assert t.sections(body)[0] == t.sections(TOOLS_JA)[0].replace("# ツール\n", "# ツール {#tools}\n")
    assert body.endswith("## エラー {#errors}\n\nファンクションから送出します。\n")


def test_link_dropped_in_a_carried_section_costs_no_repair_turn_and_the_stored_section_is_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: a reply is assembled with the carried sections before its structure is checked, so a link
    the model lost in a section this run discards anyway is no finding: one call, and the published intro is
    the stored one, link and all."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    write(root / "docs" / "tools.md", TOOLS.replace("Raise to signal a failure.", "Raise `ToolError` to fail."))
    reply = TOOLS_JA.replace("[ホーム](index.md#install)から", "ホームから").replace(
        "失敗を伝えるには例外を送出します。", "失敗するには `ToolError` を送出します。"
    )
    fake = FakeTranslator([reply])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, err, out.split("\n")[0]) == (0, "", "translated: tools.md (1 of 3 sections)")
    assert [len(conversation) for conversation in fake.conversations] == [1]  # one call, no repair turn
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    assert t.sections(body)[0] == t.sections(TOOLS_JA)[0].replace("# ツール\n", "# ツール {#tools}\n")
    assert body.endswith("## エラー {#errors}\n\n失敗するには `ToolError` を送出します。\n")


def test_removed_english_section_is_reassembled_with_no_client_but_an_edited_one_needs_credentials_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool-defined, in three runs: (1) when English sections are only removed or reordered, every remaining
    section still has its recorded translation, so the page is rebuilt from them with no model call and no
    client, hence no credentials; (2) once some page has an edited section the run calls the model, and
    missing credentials stop it before any page, rebuildable ones included, is written; (3) with credentials
    that run rebuilds the one page and retranslates the edited section of the other."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)

    def no_credentials() -> t.Translator:
        raise t.ConfigError("no API credentials: set ANTHROPIC_API_KEY")

    monkeypatch.setattr(t, "anthropic_translator", no_credentials)
    write(root / "docs" / "tools.md", TOOLS.split("## Errors")[0].rstrip("\n") + "\n")

    code, out, _ = run(capsys, root, "translate", "--lang", "ja")

    assert (code, out.split("\n")[0]) == (0, "translated: tools.md (0 of 2 sections)")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    previous = TOOLS_JA.split("## エラー")[0].rstrip("\n") + "\n"
    assert body == previous.replace("# ツール\n", "# ツール {#tools}\n").replace(
        "## 最初のツール\n", "## 最初のツール {#your-first-tool}\n"
    )
    assert run(capsys, root, "status")[1] == snapshot("ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable\n")

    write(root / "docs" / "tools.md", TOOLS.split("## Your first tool")[0].rstrip("\n") + "\n")
    write(root / "docs" / "index.md", INDEX.replace("Welcome to MCP.", "Welcome!"))
    code, out, err = run(capsys, root, "translate", "--lang", "ja")

    assert (code, out, err) == snapshot((2, "", "translations: no API credentials: set ANTHROPIC_API_KEY\n"))
    assert run(capsys, root, "status", "--lang", "ja")[1] == snapshot("""\
ja (日本語): 0 missing, 2 outdated, 2 current, 0 removable
  outdated  index.md  (English changed in: the introduction (everything before the first `##` heading))
  outdated  tools.md  (English sections removed or reordered)
""")

    fake = FakeTranslator([INDEX_JA.replace("MCP へようこそ。", "ようこそ！")])
    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, err, fake.replies, out.split("\n")[:2]) == snapshot(
        (0, "", [], ["translated: index.md (1 of 2 sections)", "translated: tools.md (0 of 1 sections)"])
    )


def test_a_failing_page_does_not_stop_the_run_and_the_exit_code_is_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: an API error, a refusal or a truncated reply fails that page only; later pages are still
    written, the failures are reported on stderr, usage is totalled, and the run exits 1."""
    root = make_repo(tmp_path)
    refusal = t.Completion("", t.Usage(10, 0, 0, 0), "refusal")
    truncated = t.Completion(TOOLS_JA[:40], t.Usage(10, 64_000, 0, 0), "max_tokens")
    fake = FakeTranslator([t.PageError("API request failed: overloaded"), truncated, refusal, NOTICES_JA])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, out, err) == snapshot(
        (
            1,
            """\
translated: i18n/notices.md (4 of 4 sections)
usage: 1020 input / 64400 output / 900 cache-write / 100 cache-read tokens
""",
            """\
error: index.md: API request failed: overloaded
error: tools.md: the reply was cut off at 64000 output tokens
error: translations.md: the model declined to translate this page
""",
        )
    )
    assert not (root / "i18n" / "ja" / "pages").exists()
    assert (root / "i18n" / "ja" / "notices.md").is_file()


def test_rejected_credentials_stop_the_run_with_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Tool-defined: an authentication failure is configuration, not a page problem: nothing more is tried."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([t.ConfigError("the API rejected the credentials: invalid x-api-key"), INDEX_JA])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, out, err) == snapshot((2, "", "translations: the API rejected the credentials: invalid x-api-key\n"))
    assert fake.replies == [INDEX_JA]


def test_repair_turn_feeds_the_findings_back_and_accepts_the_fixed_reply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: a reply that drops a code span and mistypes an admonition gets its findings appended to
    the conversation; the corrected second reply is published."""
    root = make_repo(tmp_path)
    broken = TOOLS_JA.replace("`async` に", "非同期に").replace("!!! note", "!!! warning")
    fake = FakeTranslator([INDEX_JA, broken, TOOLS_JA, TRANSLATIONS_JA, NOTICES_JA])

    code, _, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, err, fake.replies) == (0, "", [])
    assert [message.role for message in fake.conversations[2]] == ["user", "assistant", "user"]
    assert fake.conversations[2][1] == t.Message("assistant", broken)
    assert fake.conversations[2][2].content == snapshot("""\
Your translation broke the following structural rules. Fix each problem and return the
full corrected page, changing nothing else:

- missing inline code ['async']: copy every `code span` of the English
- block markers ['!!! warning'] vs ['!!! note'] in the English: keep each `!!!`/`???`/`===` line and its type\
""")


FENCE_JA = '```python title="server.py"\n--8<-- "docs_src/server.py"\n```\n\n'
# The page's fence count kept, but the code block moved from its own `##` section into the next one.
FENCE_MOVED_JA = TOOLS_JA.replace(FENCE_JA, "").replace("## エラー\n\n", "## エラー\n\n" + FENCE_JA)


def test_code_block_moved_into_another_section_is_repaired_not_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: fences are counted section by section, so a reply that keeps every code block but puts
    one under the wrong `##` heading gets a finding per section for the repair turn instead of the English
    code spliced under the wrong prose; the corrected reply is published."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([FENCE_MOVED_JA, TOOLS_JA])

    code, _, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "tools.md", translator=fake)

    assert (code, err, fake.replies) == (0, "", [])
    assert fake.conversations[1][2].content == snapshot("""\
Your translation broke the following structural rules. Fix each problem and return the
full corrected page, changing nothing else:

- ## Your first tool: 0 code fences vs 1 in the English: keep each where it is, add none
- ## Errors: 1 code fences vs 0 in the English: keep each where it is, add none\
""")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    assert body.endswith("## エラー {#errors}\n\n失敗を伝えるには例外を送出します。\n")


def test_code_block_moved_out_of_a_retranslated_section_gets_repair_turns_like_any_other_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: on an update the same slip (the retranslated section's reply swallows the code block of
    the carried section before it) is fed back for repair rather than failing the page outright; the carried
    section is the stored one by then, so only the retranslated section's extra fence is named, and the fixed
    reply is assembled with the carried sections."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    write(root / "docs" / "tools.md", TOOLS.replace("Raise to signal a failure.", "Raise `ToolError` to fail."))
    fixed = TOOLS_JA.replace("失敗を伝えるには例外を送出します。", "失敗するには `ToolError` を送出します。")
    moved = FENCE_MOVED_JA.replace("失敗を伝えるには例外を送出します。", "失敗するには `ToolError` を送出します。")
    fake = FakeTranslator([moved, fixed])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, err, fake.replies, out.split("\n")[0]) == (0, "", [], "translated: tools.md (1 of 3 sections)")
    assert fake.conversations[1][2].content == snapshot("""\
Your translation broke the following structural rules. Fix each problem and return the
full corrected page, changing nothing else:

- ## Errors: 1 code fences vs 0 in the English: keep each where it is, add none\
""")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    assert body == TOOLS_JA.replace("# ツール\n", "# ツール {#tools}\n").replace(
        "## 最初のツール\n", "## 最初のツール {#your-first-tool}\n"
    ).replace(
        "## エラー\n\n失敗を伝えるには例外を送出します。",
        "## エラー {#errors}\n\n失敗するには `ToolError` を送出します。",
    )


def test_shortened_list_and_table_are_fed_back_for_repair_before_the_page_is_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: a reply that cuts a list short behind a note in the target language and drops a table
    row passes every other check, so the item and row counts are what send it back; the full reply is
    published."""
    root = make_repo(tmp_path)
    write(root / "docs" / "translations.md", LISTED)
    shortened = LISTED_JA.replace("    1. 入れ子\n* さん\n", "（以下同様）\n").replace("| c | d |\n", "")
    fake = FakeTranslator([shortened, LISTED_JA])

    code, _, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "translations.md", translator=fake)

    assert (code, err, fake.replies) == (0, "", [])
    assert fake.conversations[1][2].content == snapshot("""\
Your translation broke the following structural rules. Fix each problem and return the
full corrected page, changing nothing else:

- the introduction (everything before the first `##` heading): 2 list items vs 4 in the English: translate them one for one, dropping none
- the introduction (everything before the first `##` heading): 3 table rows vs 4 in the English: translate them one for one, dropping none\
""")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "translations.md").read_text(encoding="utf-8"))[1]
    assert body == LISTED_JA.replace("# 翻訳について\n", "# 翻訳について {#translations}\n")


def test_page_still_broken_after_two_repair_turns_fails_and_keeps_the_previous_translation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: three structurally wrong replies (first try + two repairs) fail the page; the file that
    was published before stays byte for byte."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    before = (root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8")
    missing_fence = TOOLS_JA.replace('```python title="server.py"\n--8<-- "docs_src/server.py"\n```\n\n', "")
    fake = FakeTranslator([missing_fence] * 3)

    code, _, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "tools.md", translator=fake)

    assert (code, fake.replies) == (1, [])
    assert err == snapshot(
        "error: tools.md: unfixed after 2 repairs: ## Your first tool: 0 code fences vs 1 in the English: keep each where it is, add none\n"
    )
    assert (root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8") == before


def test_status_classifies_each_page_against_the_current_english_and_lists_removable_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: a mangled provenance block reads as missing (with the reason, so the next run redoes the
    page whole), an edited English section as outdated (naming it), and a generated file whose page left the
    translatable set (excluded here; dropped from the nav works the same) as removable, with its `git rm`."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    index = root / "i18n" / "ja" / "pages" / "index.md"
    write(index, index.read_text(encoding="utf-8").replace("  tool: 1\n", ""))
    write(root / "docs" / "tools.md", TOOLS.replace("Raise to signal a failure.", "Raise `ToolError` to fail."))
    write(root / "i18n" / "languages.yml", LANGUAGES.replace("[migration.md]", "[migration.md, translations.md]"))

    assert run(capsys, root, "status", "--lang", "ja") == snapshot(
        (
            0,
            """\
ja (日本語): 1 missing, 1 outdated, 1 current, 1 removable
  missing   index.md  (unreadable front matter, retranslated whole)
  outdated  tools.md  (English changed in: ## Errors)
  removable translations.md  (git rm i18n/ja/pages/translations.md)
""",
            "",
        )
    )


def staged_page(root: Path, page: str) -> str:
    return (root / ".build" / "i18n" / "ja" / "docs" / page).read_text(encoding="utf-8")


def test_stage_overlays_translations_injects_notices_and_rewrites_api_links(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: the ja tree is the English docs minus `api/`; a current page is served translated with
    the collapsed machine-translation notice under its H1 (English wording while the notices page itself is
    untranslated), an untranslated or excluded page is English (front matter dropped) with the
    shown-in-English notice, links into `api/` go to the English site's reference, page-relative like the
    notice links so they hold under any path prefix, and assets ride along."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([INDEX_JA])
    assert run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", translator=fake)[0] == 0
    write(root / "docs" / "api" / "mcp" / "index.md", "# API stub\n")

    code, out, err = run(capsys, root, "stage", "--lang", "ja")

    assert (code, out, err) == (0, "staged ja at .build/i18n/ja/docs\n", "")
    assert staged_page(root, "index.md") == snapshot("""\
# ホーム {#home}

??? note "Machine translation"

    Machine translated; the [English page](../) is authoritative. See [Translations](translations.md).

MCP へようこそ。[ツール](tools.md#errors)または [API](../api/mcp/) を参照してください。

## インストール {#install}

`pip install mcp` を実行し、[Python](https://www.python.org/) のドキュメントを読みます。
""")
    assert staged_page(root, "tools.md") == snapshot("""\
# Tools

!!! note "Shown in English"

    Not translated yet; [Translations](translations.md) explains why.

A **tool** is a function the model can call; start at [home](index.md#install).

## Your first tool

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "Heads up"
    Every tool is `async` friendly.

## Errors

Raise to signal a failure.
""")
    assert staged_page(root, "migration.md") == snapshot("""\
# Migration

!!! note "Shown in English"

    Not translated yet; [Translations](translations.md) explains why.

See [errors](tools.md#errors).
""")
    assert staged_page(root, "translations.md") == snapshot("""\
# Translations

!!! note "Shown in English"

    Not translated yet; [Translations](translations.md) explains why.

How this works.
""")
    assert staged_page(root, "img/logo.svg") == "<svg/>\n"
    assert not (root / ".build" / "i18n" / "ja" / "docs" / "api").exists()
    assert json.loads((root / ".build" / "i18n" / "ja" / "titles.json").read_text(encoding="utf-8")) == snapshot(
        {"index.md": "ホーム", "migration.md": "Migration", "tools.md": "Tools", "translations.md": "Translations"}
    )


def test_stage_serves_an_outdated_translation_exactly_as_generated_and_a_missing_one_in_english(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: after English-only edits under published translations, a page whose English sections were
    reordered, edited and added to is staged byte for byte as it was generated (its ids and code were pinned
    against its own English then), under the translated "outdated" notice linking today's English page; a page
    whose generated file is unusable is staged in English under the "english" notice."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    generated = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    intro, first_tool, errors = t.sections(TOOLS.replace("Raise to signal a failure.", "Raise `ToolError`."))
    write(root / "docs" / "tools.md", intro + errors + first_tool + "\n## More\n\nText.\n")
    index = root / "i18n" / "ja" / "pages" / "index.md"
    write(index, index.read_text(encoding="utf-8").replace("  tool: 1\n", ""))

    code, out, err = run(capsys, root, "stage", "--lang", "ja")

    assert (code, out, err) == (0, "staged ja at .build/i18n/ja/docs\n", "")
    staged = staged_page(root, "tools.md")
    assert staged == snapshot("""\
# ツール {#tools}

!!! note "英語版より古い翻訳"

    一部が古い可能性があります。[英語版](../tools/)と比べてください。

**ツール**はモデルが呼び出せる関数です。[ホーム](index.md#install)から始めましょう。

## 最初のツール {#your-first-tool}

```python title="server.py"
--8<-- "docs_src/server.py"
```

!!! note "注意"
    どのツールも `async` に対応しています。

## エラー {#errors}

失敗を伝えるには例外を送出します。
""")
    assert staged.split("\n\n", 3)[3] == generated.split("\n\n", 1)[1]  # after the notice: the generated body
    assert staged_page(root, "index.md").split("\n")[:3] == ["# Home", "", '!!! note "英語で表示"']


def test_stage_keeps_showing_the_generated_code_block_after_its_english_changes_until_the_page_is_retranslated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined, and the price of serving pages as generated: an edit inside an English code fence reaches a
    language site only with the next translate run (which copies the fence from the English whatever the model
    replies); until then the page shows the fence it was generated with, under the "outdated" notice."""
    root = make_repo(tmp_path)
    translate_all(capsys, root)
    write(root / "docs" / "tools.md", TOOLS.replace('title="server.py"', 'title="app.py"'))

    code, _, err = run(capsys, root, "stage", "--lang", "ja")

    staged = staged_page(root, "tools.md")
    assert (code, err, staged.split("\n")[2]) == (0, "", '!!! note "英語版より古い翻訳"')
    assert ('title="server.py"' in staged, 'title="app.py"' in staged) == (True, False)

    assert run(capsys, root, "translate", "--lang", "ja", translator=FakeTranslator([TOOLS_JA]))[0] == 0
    code, _, err = run(capsys, root, "stage", "--lang", "ja")

    staged = staged_page(root, "tools.md")
    assert (code, err, staged.split("\n")[2]) == (0, "", '??? note "機械翻訳"')
    assert ('title="server.py"' in staged, 'title="app.py"' in staged) == (False, True)


def test_notice_links_climb_from_the_staged_page_to_the_english_page_and_this_sites_translations_page() -> None:
    """Tool-defined: links are written relative to the page's source path, as the renderer reads them: the
    English page is the same path one site up (out of the page's directory, then out of the language site)
    and the translations page is this site's own `translations.md`, so no link names a host or a path prefix
    and a mirrored copy of the sites keeps working."""
    notice = t.Notice('The "outdated" one', "Compare the [English page](ENGLISH_PAGE); see [why](TRANSLATIONS_PAGE).")

    assert t.render_notice(notice, "outdated", "servers/deep/page.md") == snapshot("""\
!!! note "The 'outdated' one"

    Compare the [English page](../../../servers/deep/page/); see [why](../../translations.md).\
""")
    assert t.render_notice(notice, "translated", "servers/index.md") == snapshot("""\
??? note "The 'outdated' one"

    Compare the [English page](../../servers/); see [why](../translations.md).\
""")


def test_stage_that_stops_part_way_leaves_no_titles_file_from_an_earlier_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: `titles.json` tells `build_config.py --lang` the tree beside it is complete, so a run
    that fails midway (here an excluded page vanished from `docs/`) must not leave the previous run's behind."""
    root = make_repo(tmp_path)
    assert run(capsys, root, "stage", "--lang", "ja")[0] == 0
    titles = root / ".build" / "i18n" / "ja" / "titles.json"
    listed_before = titles.is_file()
    (root / "docs" / "migration.md").unlink()

    code, out, err = run(capsys, root, "stage", "--lang", "ja")

    assert (listed_before, code, out, titles.exists()) == (True, 2, "", False)
    assert err.startswith(f"translations: cannot read {root / 'docs' / 'migration.md'}: ")  # then the OS's wording


def test_stage_without_lang_stages_every_language_in_the_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: one invocation assembles every language's tree (the site build's single staging pass);
    a language with no prompt inputs yet still stages, in English."""
    root = make_repo(tmp_path)
    write(
        root / "i18n" / "languages.yml", LANGUAGES + "  - code: ko\n    name: 한국어\n    theme: ko\n    hreflang: ko\n"
    )

    code, out, err = run(capsys, root, "stage")

    assert (code, out, err) == (0, "staged ja at .build/i18n/ja/docs\nstaged ko at .build/i18n/ko/docs\n", "")
    listed = [(root / ".build" / "i18n" / code / "titles.json").is_file() for code in ("ja", "ko")]
    assert listed == [True, True]
