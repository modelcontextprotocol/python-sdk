"""The language-site parts of the docs build config generator (`scripts/docs/build_config.py`)."""

import json
from pathlib import Path
from typing import Any, cast

import build_config
import pytest
import yaml
from inline_snapshot import snapshot

NAV: list[build_config.NavItem] = [
    {"MCP Python SDK": "index.md"},
    {"Servers": ["servers/index.md", {"Tools": "servers/tools.md"}]},
    {"Elsewhere": [{"Spec": "https://modelcontextprotocol.io/"}]},
    "troubleshooting.md",
    {"API Reference": "api/"},
]

MKDOCS: dict[str, Any] = {
    "site_name": "Test docs",
    "site_url": "https://docs.example/",
    "nav": NAV,
    "theme": {"name": "material"},
    "plugins": ["search", {"mkdocstrings": {"handlers": {"python": {"paths": ["src"]}}}}],
    "markdown_extensions": ["admonition", {"pymdownx.snippets": {"base_path": ["."], "check_paths": True}}],
}

LANGUAGES = """\
model: some-model
exclude: []
languages:
  - {code: ja, name: 日本語, theme: ja, hreflang: ja}
"""

# What `translations.py stage` records beside the staged tree: each staged page's H1 (a page without one is
# absent), which is all the config generator knows of the pages' content.
TITLES = {"index.md": "MCP Python SDK", "servers/index.md": "サーバー", "servers/tools.md": "ツール"}


def write_repo(root: Path) -> None:
    (root / "i18n").mkdir(parents=True)
    (root / "mkdocs.yml").write_text(yaml.safe_dump(MKDOCS, sort_keys=False), encoding="utf-8")
    (root / "i18n" / "languages.yml").write_text(LANGUAGES, encoding="utf-8")
    staged = build_config.staged_docs_dir("ja", root)
    for page in build_config.nav_page_paths(NAV)[:-1]:  # every page but the `api/` placeholder
        (staged / page).parent.mkdir(parents=True, exist_ok=True)
        (staged / page).write_text("staged page\n", encoding="utf-8")
    build_config.staged_titles_file("ja", root).write_text(json.dumps(TITLES, ensure_ascii=False), encoding="utf-8")


def test_language_nav_titles_sections_from_the_recorded_page_titles_but_keeps_link_labels() -> None:
    """Tool-defined: on a language site page labels go (Zensical then shows each page's translated H1) and a
    section is titled with the recorded H1 of the index page leading it; a link entry, and a section that
    leads with no titled page, keeps its English label."""
    nav = build_config.language_nav(NAV, TITLES)

    assert nav == snapshot(
        [
            "index.md",
            {"サーバー": ["servers/index.md", "servers/tools.md"]},
            {"Elsewhere": [{"Spec": "https://modelcontextprotocol.io/"}]},
            "troubleshooting.md",
            "api/",
        ]
    )


def test_alternate_lists_english_then_each_language_as_code_labelled_links_relative_to_the_site_built() -> None:
    """Tool-defined: the switcher labels each entry `code - name` and announces the hreflang; its links are
    relative to the site the config builds (the language sites under the English one, which is one level up
    from them), so the theme renders them page-relative and no host or path prefix is ever named."""
    languages = [build_config.Language("zh", "简体中文", "zh", "zh-Hans")]
    assert build_config.alternate(languages) == snapshot(
        [
            {"name": "en - English", "link": "./", "lang": "en"},
            {"name": "zh - 简体中文", "link": "zh/", "lang": "zh-Hans"},
        ]
    )
    assert build_config.alternate(languages, "zh") == snapshot(
        [
            {"name": "en - English", "link": "../", "lang": "en"},
            {"name": "zh - 简体中文", "link": "../zh/", "lang": "zh-Hans"},
        ]
    )


def test_lang_config_builds_the_staged_tree_into_site_code_without_an_api_reference(tmp_path: Path) -> None:
    """Tool-defined: `--lang ja` writes mkdocs.ja.gen.yml pointing Zensical at the staged tree (repo-relative),
    building into site/ja/ under the ja URL prefix and theme language, with mkdocstrings dropped, snippet path
    checks off (a stale include in a stored translation renders empty rather than failing the build), the API
    entry turned into a link up to the English reference, section titles from the `titles.json` staged
    beside the tree, and the switcher with links relative to this site."""
    write_repo(tmp_path)

    written = build_config.build_config("ja", tmp_path)

    config = cast(dict[str, Any], yaml.safe_load(written.read_text(encoding="utf-8")))
    keys = ("docs_dir", "site_dir", "site_url", "theme", "plugins", "markdown_extensions", "nav", "extra")
    picked = {key: config[key] for key in keys}
    assert (written.name, picked) == snapshot(
        (
            "mkdocs.ja.gen.yml",
            {
                "docs_dir": ".build/i18n/ja/docs",
                "site_dir": "site/ja",
                "site_url": "https://docs.example/ja/",
                "theme": {"name": "material", "language": "ja"},
                "plugins": ["search"],
                "markdown_extensions": [
                    "admonition",
                    {"pymdownx.snippets": {"base_path": ["."], "check_paths": False}},
                ],
                "nav": [
                    "index.md",
                    {"サーバー": ["servers/index.md", "servers/tools.md"]},
                    {"Elsewhere": [{"Spec": "https://modelcontextprotocol.io/"}]},
                    "troubleshooting.md",
                    {"API Reference": "../api/mcp/"},
                ],
                "extra": {
                    "alternate": [
                        {"name": "en - English", "link": "../", "lang": "en"},
                        {"name": "ja - 日本語", "link": "../ja/", "lang": "ja"},
                    ]
                },
            },
        )
    )


def test_lang_config_for_a_language_not_in_the_registry_exits_with_a_message(tmp_path: Path) -> None:
    """Tool-defined: an unknown code is a usage error naming the registry, not a traceback."""
    write_repo(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        build_config.build_config("xx", tmp_path)

    assert excinfo.value.code == snapshot("build_config: unknown language 'xx' (see i18n/languages.yml)")
