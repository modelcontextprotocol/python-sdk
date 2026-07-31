"""Shared helpers for the docs translation tool tests: a throwaway repo layout and a scripted model."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from i18n.client import Message
from i18n.config import Language

CODE = "xx"
SITE_NAME = "Test docs"
LANGUAGE = Language(CODE, "Testish", "en", CODE, "latin", True)

# A representative English page: pinned anchors, an admonition, a table, a
# link, an inline code span and a fenced snippet include.
ENGLISH = """\
# Tools {#tools}

MCP tools are functions the server exposes; see [Prompts](prompts.md).

!!! note "Naming"
    Call `tool()` once per function.

| Column | Meaning |
| ------ | ------- |
| name | the tool name |

## Registering a tool {#registering-a-tool}

```python
--8<-- "docs_src/tools/tutorial001.py"
```

The `Context` object is always available.
"""

# The same page "translated": prose reworded, machinery byte-identical.
TRANSLATED = """\
# Tuulzen {#tools}

Xx MCP tuulzen zint funktien der server; zeu [Prompten](prompts.md).

!!! note "Naimung"
    Kall `tool()` einmol per funktien.

| Kolumne | Bedoitung |
| ------ | ------- |
| naam | de tool naam |

## Ein tuul registrieren {#registering-a-tool}

```python
--8<-- "docs_src/tools/tutorial001.py"
```

Xx `Context` objekt zint immer verfuegbar.
"""


@dataclass
class Repo:
    """A minimal repository the tool can run against."""

    root: Path
    language: Language = field(default_factory=lambda: LANGUAGE)

    @property
    def code(self) -> str:
        return self.language.code

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def i18n(self) -> Path:
        return self.root / "i18n"

    @property
    def pages(self) -> Path:
        return self.i18n / "languages" / self.code / "pages"

    @property
    def state_path(self) -> Path:
        return self.i18n / "languages" / self.code / "state.json"

    @property
    def nav_path(self) -> Path:
        return self.i18n / "languages" / self.code / "nav.yml"

    def write_english(self, page: str, text: str) -> Path:
        path = self.docs / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_translation(self, page: str, text: str) -> Path:
        path = self.pages / page
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


def make_repo(root: Path, *, nav: Sequence[Any] = ("index.md",), glossary: dict[str, object] | None = None) -> Repo:
    """Lay out mkdocs.yml, docs/ and i18n/ for one language `xx`.

    `nav` entries are the mkdocs shapes: a bare page path, or a `{label: page-or-URL-or-list}` mapping.
    """
    repo = Repo(root)
    config = {"site_name": SITE_NAME, "site_url": "https://docs.example/", "nav": list(nav)}
    (root / "mkdocs.yml").write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    repo.docs.mkdir()
    (repo.i18n / "languages" / CODE).mkdir(parents=True)
    (repo.i18n / "languages.yml").write_text(
        "languages:\n"
        f"  - code: {CODE}\n"
        "    name: Testish\n"
        "    theme_language: en\n"
        f"    hreflang: {CODE}\n"
        "    script: latin\n"
        "    enabled: true\n"
        "exclude_pages:\n"
        "  - migration.md\n"
        "  - api/**\n"
        "models:\n"
        "  translate: model-t\n"
        "  verify: model-v\n",
        encoding="utf-8",
    )
    (repo.i18n / "general-prompt.md").write_text("General rules.\n", encoding="utf-8")
    (repo.i18n / "languages" / CODE / "instructions.md").write_text("Testish rules.\n", encoding="utf-8")
    write_glossary(repo, glossary or {"version": 1, "keep_in_source_language": ["MCP", "Context"], "terms": []})
    banners = repo.i18n / "banners" / "en"
    banners.mkdir(parents=True)
    (banners / "disclosure.md").write_text(
        '??? info "Machine-translated"\n    English original: {english_url}. Report: {translations_page_url}.\n',
        encoding="utf-8",
    )
    (banners / "outdated.md").write_text('!!! warning "Behind"\n    See {english_url}.\n', encoding="utf-8")
    (banners / "untranslated.md").write_text('!!! note "Not yet"\n    See {translations_page_url}.\n', encoding="utf-8")
    (banners / "stale.md").write_text(
        '!!! warning "Being refreshed"\n    See {translations_page_url}.\n', encoding="utf-8"
    )
    (banners / "english-only.md").write_text(
        '!!! note "English only"\n    See {translations_page_url}.\n', encoding="utf-8"
    )
    return repo


def write_glossary(repo: Repo, glossary: dict[str, object]) -> None:
    path = repo.i18n / "languages" / repo.code / "glossary.json"
    path.write_text(json.dumps(glossary, ensure_ascii=False), encoding="utf-8")


@dataclass
class Call:
    """One recorded model request."""

    model: str
    system: str
    messages: list[Message]
    max_tokens: int


class FakeTranslator:
    """A `Translator` that replies from a script and records every request."""

    def __init__(self, replies: Sequence[str]) -> None:
        self.replies = list(replies)
        self.calls: list[Call] = []

    def complete(self, *, model: str, system: str, messages: Sequence[Message], max_tokens: int) -> str:
        self.calls.append(Call(model, system, list(messages), max_tokens))
        return self.replies.pop(0)


def nav_reply(renderings: Mapping[str, str]) -> str:
    """A model reply carrying the nav label map, prose around it as a real reply may."""
    return f"Here is the label map:\n{json.dumps(dict(renderings), ensure_ascii=False, indent=2)}\nDone."
