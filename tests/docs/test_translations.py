"""The documentation translation tool (`scripts/docs/translations.py`).

Everything here is tool-defined behaviour: what the model must never change is
re-imposed from the English page (or, for links, checked against it), unchanged
sections survive re-translation byte for byte, a page's state lives in its own
front matter, and a language
site is the English tree with translations laid over it and a notice on every
page. The model is a scripted fake and the repository a `tmp_path` tree, so
every test is offline and deterministic.
"""

import json
import posixpath
from collections.abc import Callable, Sequence
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
    reviewers: [a-reviewer]
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
    """A repository with two English prose pages, an excluded page and the ja inputs, nothing translated."""
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


def translate_both(capsys: pytest.CaptureFixture[str], root: Path) -> None:
    """Publish faithful translations of both pages and the notices through the real command."""
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
    a number, and a block that is off-schema reads as no provenance at all."""
    provenance = t.Provenance(("1234567890123456", "00ff00ff00ff00ff"), "abcdef")
    text = t.with_provenance("# 本文\n", provenance)

    assert text == snapshot("""\
---
translation:
  sections: ['1234567890123456', 00ff00ff00ff00ff]
  inputs: abcdef
  tool: 1
---
# 本文
""")
    front_matter, body = t.split_front_matter(text)
    assert (t.read_provenance(front_matter), body) == (provenance, "# 本文\n")
    assert t.read_provenance("translation: {sections: [], inputs: x, tool: 99}\n") is None
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
    assert repo.render_ids(pinned) == ids


def test_heading_the_source_scan_cannot_pin_makes_the_page_an_error(tmp_path: Path) -> None:
    """Tool-defined: a setext heading renders but is not an ATX heading at column 0, so ids cannot be paired
    positionally; the page is refused rather than mis-pinned."""
    repo = t.load_repo(make_repo(tmp_path))

    with pytest.raises(t.PageError) as excinfo:
        repo.heading_ids("# Title\n\nSetext\n------\n")

    assert str(excinfo.value) == snapshot("the page renders 2 headings but 1 are ATX headings at column 0")


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


@pytest.mark.parametrize(
    ("reply", "fences_restored", "findings"),
    [
        pytest.param(
            ENGLISH.replace("## Step\n\n## Step\n", "## Step\n"),
            True,
            snapshot(["3 headings vs 4 in the English: keep every heading, and no others"]),
            id="heading-dropped",
        ),
        pytest.param(
            ENGLISH.replace("## Step\n\n", "### Step\n\n"),
            True,
            snapshot(["`Step` is a level-3 heading but `Step` is level 2"]),
            id="heading-level",
        ),
        pytest.param(
            ENGLISH.replace('hl_lines="1"\n', 'hl_lines="1"\n```\n\n```text\n'),
            False,
            snapshot(["2 code fences vs 1 in the English: keep each code block, add none"]),
            id="fence-added",
        ),
        pytest.param(
            ENGLISH.replace("\n```\n\n## Step", "\n\n## Step"),
            False,
            snapshot(
                [
                    "the code fence opened on line 7 is never closed",
                    "2 headings vs 4 in the English: keep every heading, and no others",
                ]
            ),
            id="fence-unclosed",
        ),
        pytest.param(
            ENGLISH.replace("[logo](img/logo.svg)", "[logo](img/logo.svg), [more](more.md)"),
            True,
            snapshot(["unexpected links to ['more.md']: add no links of your own"]),
            id="link-added",
        ),
        pytest.param(
            ENGLISH.replace("tools.md#errors", "tools.md#エラー"),
            True,
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
            True,
            snapshot(
                [
                    "missing links to ['tools.md#errors']: keep every link of the English where it is",
                    "unexpected links to ['tools.md#errors']: add no links of your own",
                ]
            ),
            id="link-moved-to-another-section",
        ),
        pytest.param(
            ENGLISH.replace("https://spec.example/", "https://spec.example/ja/"),
            True,
            snapshot(
                [
                    "missing links to ['https://spec.example/']: keep every link of the English where it is",
                    "unexpected links to ['https://spec.example/ja/']: add no links of your own",
                ]
            ),
            id="url-changed",
        ),
    ],
)
def test_reimpose_names_each_structural_mismatch(reply: str, fences_restored: bool, findings: list[str]) -> None:
    """Tool-defined: a fence or heading count or level the reply gets wrong cannot be repaired positionally,
    and a link target its English section lacks (mangled, added, dropped or moved across sections) is never
    rewritten, so each becomes a finding for the repair turn; `fences_restored` tells stage whether the code
    is still trustworthy."""
    result = t.reimpose(ENGLISH, ["guide", "the-__init__-hook", "step", "step_1"], reply)

    assert isinstance(result, t.Mismatch)
    assert result.fences_restored is fences_restored
    assert result.findings == findings


def test_validate_flags_code_spans_markers_tables_banned_terms_and_abridgement() -> None:
    """Tool-defined: what re-imposition cannot fix is reported for the repair turn; a banned rendering
    inside code is not prose, and a link label or anything the English itself says is not an abridgement."""
    glossary = t.Glossary(("MCP",), (t.Term("tool", "ツール", "", ("道具",)),))
    table = "    | a | b |\n    |---|---|\n    | 1 | 2 |\n"
    english = f'# T\n\nUse `ctx` and `run()`. See [Translations](t.md), not [...].\n\n!!! tip "Hint"\n{table}'
    faithful = (
        "# T\n\n`ctx` と `run()` を使います。`道具` はコード。[Translations](t.md) 参照、[...] 以外。\n\n"
        f'!!! tip "ヒント"\n{table}'
    )
    broken = (
        "# T\n\n`ctx` と `run` を使う道具です。[translation continues below]\n\n"
        '!!! note "ヒント"\n    | a | b |\n    |---|---|\n<!-- rest of the table omitted -->\n'
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
            "table rows [2] vs [3] in the English",
            "banned rendering '道具' of 'tool' appears: use 'ツール'",
            "placeholder '<!-- rest of the table omitted -->': translate the whole page, never abridge it",
            "placeholder '[translation continues below]': translate the whole page, never abridge it",
        ]
    )


def test_glossary_with_an_unknown_key_stops_status_with_exit_2_but_never_breaks_stage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: the glossary schema is closed, so a misspelt or retired key stops the commands that prompt
    with it (exit 2); the site build's `stage` never reads prompt inputs, so a broken one cannot fail a build."""
    root = make_repo(tmp_path)
    glossary = root / "i18n" / "ja" / "glossary.json"
    write(glossary, json.dumps({"keep": [], "terms": [{"source": "a", "target": "b", "enforce": True}]}))

    code, out, err = run(capsys, root, "status")

    assert (code, out) == (2, "")
    assert err.replace(str(glossary), "GLOSSARY") == snapshot(
        "translations: GLOSSARY: terms[0] has unknown keys ['enforce']\n"
    )
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
  inputs: e3a337c884303a54
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
        (0, "ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable, 0 english-fallback\n", "")
    )


def test_translate_limit_caps_the_pages_of_a_run_but_not_an_explicit_page_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: `--limit N` translates the first N selected pages in nav order and says how many it left;
    `--pages` names exactly the pages to run, so the cap does not apply to it."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([INDEX_JA, INDEX_JA, TOOLS_JA])

    code, out, _ = run(capsys, root, "translate", "--lang", "ja", "--limit", "1", translator=fake)

    assert (code, out.split("\n")[:2]) == snapshot(
        (
            0,
            [
                "ja: 1 of 4 selected pages this run (--limit); run again for more",
                "translated: index.md (2 of 2 sections)",
            ],
        )
    )
    assert not (root / "i18n" / "ja" / "pages" / "tools.md").exists()

    argv = ("translate", "--lang", "ja", "--pages", "index.md", "tools.md", "--limit", "1")
    code, out, _ = run(capsys, root, *argv, translator=fake)

    assert (code, fake.replies, out.split("\n")[:2]) == snapshot(
        (0, [], ["translated: index.md (2 of 2 sections)", "translated: tools.md (3 of 3 sections)"])
    )


def test_docs_translate_model_overrides_the_registry_model_for_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool-defined: calls use the registry's model unless `DOCS_TRANSLATE_MODEL` names another one to
    trial, and neither is ever written into the generated page."""
    root = make_repo(tmp_path)
    monkeypatch.delenv("DOCS_TRANSLATE_MODEL", raising=False)
    fake = FakeTranslator([INDEX_JA, INDEX_JA])
    assert run(capsys, root, "translate", "--lang", "ja", "--limit", "1", translator=fake)[0] == 0
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
    translate_both(capsys, root)
    fake = FakeTranslator([INDEX_JA.replace("へようこそ", "へようこそ！")])

    code, out, _ = run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", translator=fake)

    assert (code, out.split("\n")[0]) == (0, "translated: index.md (2 of 2 sections)")
    assert fake.conversations[0] == [t.Message("user", t.translate_request(INDEX))]
    assert "MCP へようこそ！" in (root / "i18n" / "ja" / "pages" / "index.md").read_text(encoding="utf-8")
    assert run(capsys, root, "status")[1] == snapshot(
        "ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable, 0 english-fallback\n"
    )

    code, _, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "nope.md", translator=fake)

    assert (code, err) == snapshot(
        (2, "translations: not translatable pages (nav paths such as servers/tools.md): ['nope.md']\n")
    )


def test_translate_grep_rewrites_only_matching_sections_and_keeps_the_rest_byte_identical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: `--grep` selects current pages whose English matches, shows the previous translation and
    opens only the matching sections; the model's rewording elsewhere is discarded by carry-forward, so the
    diff is bounded."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    path = root / "i18n" / "ja" / "pages" / "tools.md"
    before = t.split_front_matter(path.read_text(encoding="utf-8"))[1]
    reworded_everywhere = TOOLS_JA.replace("。", "！").replace("失敗を伝えるには", "しっぱいを伝えるには")
    fake = FakeTranslator([reworded_everywhere])

    code, out, _ = run(capsys, root, "translate", "--lang", "ja", "--grep", "signal a failure", translator=fake)

    after = t.split_front_matter(path.read_text(encoding="utf-8"))[1]
    assert (code, out.split("\n")[0]) == (0, "translated: tools.md (1 of 3 sections)")
    assert "Sections to retranslate:\n\n- ## Errors\n\n" in fake.conversations[0][0].content
    assert f"<previous-translation>\n{before}\n</previous-translation>" in fake.conversations[0][0].content
    assert [a == b for a, b in zip(t.sections(before), t.sections(after), strict=True)] == [True, True, False]
    assert t.sections(after)[2] == snapshot("""\

## エラー {#errors}

しっぱいを伝えるには例外を送出します！
""")


def test_outdated_page_retranslates_the_changed_section_and_carries_the_rest_forward(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: editing one English section marks the page outdated; the prompt carries the previous
    translation and names that section for retranslation, and every other section keeps its previous bytes
    even though the model re-rendered them."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    write(root / "docs" / "tools.md", TOOLS.replace("Raise to signal a failure.", "Raise `ToolError` to fail."))
    reply = TOOLS_JA.replace("**ツール**は", "気まぐれな言い換え：**ツール**は").replace(
        "失敗を伝えるには例外を送出します。", "失敗するには `ToolError` を送出します。"
    )
    fake = FakeTranslator([reply])

    assert run(capsys, root, "status")[1] == snapshot("""\
ja (日本語): 0 missing, 1 outdated, 3 current, 0 removable, 0 english-fallback
  outdated  tools.md  (English changed in: ## Errors)
""")
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
    A carried section using a word the glossary has since banned is published text (`--grep` revises it), so
    it is neither a finding nor touched; the same word in the retranslated section is repaired as ever."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
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


def test_removed_english_section_is_reassembled_without_a_model_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: when English sections are only removed or reordered, every remaining section still has
    its recorded translation, so the page is rebuilt from them with zero calls."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    write(root / "docs" / "tools.md", TOOLS.split("## Errors")[0].rstrip("\n") + "\n")
    fake = FakeTranslator([])

    code, out, _ = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, out.split("\n")[0]) == (0, "translated: tools.md (0 of 2 sections)")
    body = t.split_front_matter((root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8"))[1]
    previous = TOOLS_JA.split("## エラー")[0].rstrip("\n") + "\n"
    assert body == previous.replace("# ツール\n", "# ツール {#tools}\n").replace(
        "## 最初のツール\n", "## 最初のツール {#your-first-tool}\n"
    )
    assert run(capsys, root, "status")[1].split("\n")[0] == snapshot(
        "ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable, 0 english-fallback"
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


def test_crash_inside_a_page_is_exit_3_with_a_traceback_and_nothing_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: an exception the tool does not classify is a bug in it, reported as exit 3 so the
    workflow proposes nothing, never exit 1's "some pages failed, ship the rest"."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([RuntimeError("boom"), TOOLS_JA])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, out, fake.replies) == (3, "", [TOOLS_JA])
    assert (err.split("\n")[0], err.strip("\n").split("\n")[-1]) == snapshot(
        ("Traceback (most recent call last):", "translations: internal error: RuntimeError('boom')")
    )
    assert not (root / "i18n" / "ja" / "pages").exists()


def test_rejected_credentials_stop_the_run_with_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Tool-defined: an authentication failure is configuration, not a page problem: nothing more is tried."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([t.ConfigError("the API rejected the credentials: invalid x-api-key"), INDEX_JA])

    code, out, err = run(capsys, root, "translate", "--lang", "ja", translator=fake)

    assert (code, out, err) == snapshot((2, "", "translations: the API rejected the credentials: invalid x-api-key\n"))
    assert fake.replies == [INDEX_JA]


def test_dry_run_prints_the_prompts_and_builds_no_client(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool-defined: `--dry-run` shows the shared system prompt once and each page's user message with a rough
    token count, and never constructs the API client (so it needs neither credentials nor the SDK)."""
    root = make_repo(tmp_path)

    def no_client() -> t.Translator:
        raise NotImplementedError

    monkeypatch.setattr(t, "anthropic_translator", no_client)

    code, out, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", "--dry-run")

    assert (code, err) == (0, "")
    assert out == snapshot("""\
===== system prompt, shared by every page (~67 tokens) =====
General rules.

# Target language: 日本語 (`ja`)

Japanese rules.

## Glossary

These terms always stay in English, spelled exactly like this:

- MCP
- Python

Use these renderings; the notes are binding:

- tool → ツール (never: 道具)
- server → サーバー. Katakana, long vowel kept.
===== index.md: user message (~71 tokens) =====
Translate the following Markdown page. Return only the translated page.

<english-page>
# Home

Welcome to MCP. Read about [tools](tools.md#errors) or the [API](api/mcp/index.md).

## Install

Run `pip install mcp`, then read the [Python](https://www.python.org/) docs.

</english-page>
ja: 1 page(s) selected; dry run, nothing sent (token counts are chars/4)
""")
    assert not (root / "i18n" / "ja" / "pages").exists()


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


def test_page_still_broken_after_two_repair_turns_fails_and_keeps_the_previous_translation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: three structurally wrong replies (first try + two repairs) fail the page; the file that
    was published before stays byte for byte."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    before = (root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8")
    missing_fence = TOOLS_JA.replace('```python title="server.py"\n--8<-- "docs_src/server.py"\n```\n\n', "")
    fake = FakeTranslator([missing_fence] * 3)

    code, _, err = run(capsys, root, "translate", "--lang", "ja", "--pages", "tools.md", translator=fake)

    assert (code, fake.replies) == (1, [])
    assert err == snapshot(
        "error: tools.md: unfixed after 2 repairs: 0 code fences vs 1 in the English: keep each code block, add none\n"
    )
    assert (root / "i18n" / "ja" / "pages" / "tools.md").read_text(encoding="utf-8") == before


def test_unreadable_front_matter_makes_the_page_missing_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: a generated file whose provenance block was mangled is not trusted for carry-forward; it
    reads as missing, with the reason, so the next run retranslates it whole."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    path = root / "i18n" / "ja" / "pages" / "index.md"
    write(path, path.read_text(encoding="utf-8").replace("  tool: 1\n", ""))

    assert run(capsys, root, "status")[1] == snapshot("""\
ja (日本語): 1 missing, 0 outdated, 3 current, 0 removable, 0 english-fallback
  missing   index.md  (unreadable front matter, retranslated whole)
""")


def test_editing_the_glossary_leaves_pages_current_and_status_counts_them_as_predating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: staleness is English changing, nothing else; a glossary or instructions edit only shows in
    the "predate" summary, so a one-term correction never mass-invalidates a language."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    write(root / "i18n" / "ja" / "glossary.json", json.dumps({**GLOSSARY, "keep": ["MCP", "Python", "uv"]}))

    assert run(capsys, root, "status", "--lang", "ja") == snapshot(
        (
            0,
            """\
ja (日本語): 0 missing, 0 outdated, 4 current, 0 removable, 0 english-fallback
  4 pages predate the current instructions/glossary (see `translate --grep`)
""",
            "",
        )
    )
    assert run(capsys, root, "translate", "--lang", "ja")[1] == "ja: nothing to translate\n"


def staged_page(root: Path, page: str) -> str:
    return (root / ".build" / "i18n" / "ja" / "docs" / page).read_text(encoding="utf-8")


def test_stage_overlays_translations_injects_notices_and_rewrites_api_links(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tool-defined: the ja tree is the English docs minus `api/`; a current page is served translated with
    the collapsed machine-translation notice under its H1 (English wording while the notices page itself is
    untranslated), an untranslated or excluded page is English (front matter dropped) with the
    shown-in-English notice, links into `api/` become site-absolute paths, and assets ride along."""
    root = make_repo(tmp_path)
    fake = FakeTranslator([INDEX_JA])
    assert run(capsys, root, "translate", "--lang", "ja", "--pages", "index.md", translator=fake)[0] == 0
    write(root / "docs" / "api" / "mcp" / "index.md", "# API stub\n")

    code, out, err = run(capsys, root, "stage", "--lang", "ja")

    assert (code, out, err) == (0, "staged ja at .build/i18n/ja/docs\n", "")
    assert staged_page(root, "index.md") == snapshot("""\
# ホーム {#home}

??? note "Machine translation"

    Machine translated; the [English page](/) is authoritative. See [Translations](/ja/translations/).

MCP へようこそ。[ツール](tools.md#errors)または [API](/api/mcp/) を参照してください。

## インストール {#install}

`pip install mcp` を実行し、[Python](https://www.python.org/) のドキュメントを読みます。
""")
    assert staged_page(root, "tools.md") == snapshot("""\
# Tools

!!! note "Shown in English"

    Not translated yet; [Translations](/ja/translations/) explains why.

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

    Not translated yet; [Translations](/ja/translations/) explains why.

See [errors](tools.md#errors).
""")
    assert staged_page(root, "translations.md") == snapshot("""\
# Translations

!!! note "Shown in English"

    Not translated yet; [Translations](/ja/translations/) explains why.

How this works.
""")
    assert staged_page(root, "img/logo.svg") == "<svg/>\n"
    assert not (root / ".build" / "i18n" / "ja" / "docs" / "api").exists()
    assert json.loads((root / ".build" / "i18n" / "ja" / "titles.json").read_text(encoding="utf-8")) == snapshot(
        {"index.md": "ホーム", "migration.md": "Migration", "tools.md": "Tools", "translations.md": "Translations"}
    )


def test_resolve_links_unlinks_dead_targets_keeping_the_label_as_written_inline_code_included() -> None:
    """Tool-defined: a link to a page the tree lacks keeps only its label, a dead `#fragment` is dropped (the
    whole link when it is page-local), and the label comes back exactly as written, code spans and all."""
    body = "See [`Tool` errors](gone.md), [`run()`](tools.md#nope), [`here`](#nope) and [`ok`](tools.md#errors).\n"
    ids: dict[str, set[str]] = {"index.md": set(), "tools.md": {"errors"}}

    result = t.resolve_links(body, "index.md", {".", "index.md", "tools.md"}, ids)

    assert result == snapshot("See `Tool` errors, [`run()`](tools.md), `here` and [`ok`](tools.md#errors).\n")


def resolves(docs: Path, page: str, target: str, ids: dict[str, list[str]]) -> bool:
    """Whether a relative link written on `page` reaches a file of the staged tree (and a heading it renders)."""
    path, _, fragment = target.partition("#")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else page
    return (docs / resolved).exists() and (not fragment or fragment in ids[resolved])


def dead_links(root: Path) -> list[str]:
    """Every relative link in the staged ja tree that its own (non-strict) build would warn about."""
    docs = root / ".build" / "i18n" / "ja" / "docs"
    repo = t.load_repo(root)
    texts = {path.relative_to(docs).as_posix(): path.read_text(encoding="utf-8") for path in docs.rglob("*.md")}
    ids = {page: repo.render_ids(text) for page, text in texts.items()}
    written = [(page, link.target) for page, text in texts.items() for link in t.links(text)]
    relative = [(page, target) for page, target in written if target and t.is_relative(target)]
    return [f"{page}: {target}" for page, target in relative if not resolves(docs, page, target, ids)]


def notices(root: Path) -> dict[str, str]:
    """The notice line each staged page carries."""
    docs = root / ".build" / "i18n" / "ja" / "docs"
    pages = sorted(path.relative_to(docs).as_posix() for path in docs.rglob("*.md"))
    return {page: staged_page(root, page).split("\n")[2] for page in pages}


def english_adds_a_linked_section(root: Path) -> None:
    write(root / "docs" / "tools.md", TOOLS + "\n## Brand new\n\nText.\n")
    write(
        root / "docs" / "migration.md", "# Migration\n\nSee [new](tools.md#brand-new) and [errors](tools.md#errors).\n"
    )


def english_renames_a_linked_heading(root: Path) -> None:
    write(root / "docs" / "tools.md", TOOLS.replace("## Errors", "## Failures"))
    write(root / "docs" / "index.md", INDEX.replace("tools.md#errors", "tools.md#failures"))
    write(root / "docs" / "migration.md", "# Migration\n\nSee [failures](tools.md#failures).\n")


def english_renames_the_snippet_and_adds_a_fence(root: Path) -> None:
    (root / "docs_src" / "server.py").rename(root / "docs_src" / "app.py")
    tools = TOOLS.replace("docs_src/server.py", "docs_src/app.py").replace('title="server.py"', 'title="app.py"')
    write(root / "docs" / "tools.md", tools + "\n```bash\nuv run app.py\n```\n")


def english_deletes_a_page(root: Path) -> None:
    (root / "docs" / "tools.md").unlink()
    write(root / "mkdocs.yml", MKDOCS.replace("  - Tools: tools.md\n", ""))
    write(root / "docs" / "index.md", INDEX.replace("[tools](tools.md#errors)", "tools"))
    write(root / "docs" / "migration.md", "# Migration\n\nNothing to see.\n")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        pytest.param(
            english_adds_a_linked_section,
            snapshot(
                (
                    """\
ja (日本語): 0 missing, 1 outdated, 3 current, 0 removable, 0 english-fallback
  outdated  tools.md  (English changed in: ## Brand new)
  drifted   tools.md  (served; 3 headings vs 4 in the English: keep every heading, and no others)
""",
                    [],
                    {
                        "index.md": '??? note "機械翻訳"',
                        "migration.md": '!!! note "英語で表示"',
                        "tools.md": '!!! note "英語版より古い翻訳"',
                        "translations.md": '??? note "機械翻訳"',
                    },
                )
            ),
            id="adds-a-linked-section",
        ),
        pytest.param(
            english_renames_a_linked_heading,
            snapshot(
                (
                    """\
ja (日本語): 0 missing, 2 outdated, 2 current, 0 removable, 0 english-fallback
  outdated  index.md  (English changed in: the introduction (everything before the first `##` heading))
  drifted   index.md  (served; missing links to ['tools.md#failures']: keep every link of the English where it is;\
"""
                    """ unexpected links to ['tools.md#errors']: add no links of your own)
  outdated  tools.md  (English changed in: ## Failures)
""",
                    [],
                    {
                        "index.md": '!!! note "英語版より古い翻訳"',
                        "migration.md": '!!! note "英語で表示"',
                        "tools.md": '!!! note "英語版より古い翻訳"',
                        "translations.md": '??? note "機械翻訳"',
                    },
                )
            ),
            id="renames-a-linked-heading",
        ),
        pytest.param(
            english_renames_the_snippet_and_adds_a_fence,
            snapshot(
                (
                    """\
ja (日本語): 0 missing, 1 outdated, 3 current, 0 removable, 1 english-fallback
  outdated  tools.md  (English changed in: ## Your first tool, ## Errors)
  fallback  tools.md  (served in English; 1 code fences vs 2 in the English: keep each code block, add none)
""",
                    ["tools.md: served in English (1 code fences vs 2 in the English: keep each code block, add none)"],
                    {
                        "index.md": '??? note "機械翻訳"',
                        "migration.md": '!!! note "英語で表示"',
                        "tools.md": '!!! note "英語で表示"',
                        "translations.md": '??? note "機械翻訳"',
                    },
                )
            ),
            id="renames-snippet-adds-fence",
        ),
        pytest.param(
            english_deletes_a_page,
            snapshot(
                (
                    """\
ja (日本語): 0 missing, 1 outdated, 2 current, 1 removable, 0 english-fallback
  outdated  index.md  (English changed in: the introduction (everything before the first `##` heading))
  drifted   index.md  (served; unexpected links to ['tools.md#errors']: add no links of your own)
  removable tools.md  (git rm i18n/ja/pages/tools.md)
""",
                    [],
                    {
                        "index.md": '!!! note "英語版より古い翻訳"',
                        "migration.md": '!!! note "英語で表示"',
                        "translations.md": '??? note "機械翻訳"',
                    },
                )
            ),
            id="deletes-a-page",
        ),
    ],
)
def test_stage_stays_consistent_when_english_moves_under_published_translations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: Callable[[Path], None],
    expected: tuple[str, list[str], dict[str, str]],
) -> None:
    """Tool-defined: whatever an English-only change does to pages that have published translations, the
    staged tree has no dead relative link or fragment, each page carries the notice matching what is
    served, and `status` predicted every page that falls back to English."""
    root = make_repo(tmp_path)
    translate_both(capsys, root)
    change(root)

    status = run(capsys, root, "status")[1]
    code, _, err = run(capsys, root, "stage", "--lang", "ja")

    assert code == 0
    assert dead_links(root) == []
    assert (status, err.splitlines(), notices(root)) == expected
