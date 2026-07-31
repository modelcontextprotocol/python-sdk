"""Tests for the build config generator (scripts/docs/build_config.py).

The English `build_config()` path materialises the API reference from `src/`,
so its composable parts (the language-switcher list, the repo-relative path
form) are driven directly, and the site-URL threading through a language
config runs against a throwaway repository root.
"""

from pathlib import Path
from typing import Any

import build_config
import pytest
import yaml

from i18n.config import Language, Models, Registry

JA = Language("ja", "日本語", "ja", "ja", "cjk", True)
KO = Language("ko", "한국어", "ko", "ko", "hangul", True)
DRAFT = Language("xx", "Testish", "en", "xx", "latin", False)
REGISTRY = Registry(languages=(JA, KO, DRAFT), exclude_pages=(), models=Models("model-t", "model-v"))

SITE_URL = "https://docs.example"
ENGLISH = {"name": "English", "link": "/", "lang": "en"}
JA_ENTRY = {"name": "日本語", "link": "/ja/", "lang": "ja"}
KO_ENTRY = {"name": "한국어", "link": "/ko/", "lang": "ko"}


def test_alternate_lists_english_then_every_enabled_language_by_default() -> None:
    assert build_config._alternate(REGISTRY, None, SITE_URL) == [ENGLISH, JA_ENTRY, KO_ENTRY]


def test_alternate_lists_only_the_sites_the_build_produces() -> None:
    assert build_config._alternate(REGISTRY, ["ko"], SITE_URL) == [ENGLISH, KO_ENTRY]
    # An English-only build offers no other language site.
    assert build_config._alternate(REGISTRY, [], SITE_URL) == [ENGLISH]


def test_alternate_links_follow_the_path_the_site_is_served_under() -> None:
    # A site served below the host root switches languages under that same path.
    assert build_config._alternate(REGISTRY, ["ja"], "https://mirror.example/py-sdk") == [
        {"name": "English", "link": "/py-sdk/", "lang": "en"},
        {"name": "日本語", "link": "/py-sdk/ja/", "lang": "ja"},
    ]


@pytest.mark.parametrize(
    ("codes", "message"),
    [
        (["zz"], "build_config: --switcher-languages: unknown language 'zz' (registered: ja, ko, xx)"),
        (["xx"], "build_config: --switcher-languages names disabled languages: ['xx']"),
    ],
)
def test_alternate_rejects_a_site_that_would_not_be_built(codes: list[str], message: str) -> None:
    with pytest.raises(SystemExit) as failure:
        build_config._alternate(REGISTRY, codes, SITE_URL)

    assert failure.value.code == message


def test_repo_relative_resolves_a_path_derived_from_a_symlinked_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The repository is reached through a symlink, so a path derived from the
    # resolved root (as the staged site directory is) and the unresolved root
    # disagree textually; the relative form must still come out right.
    real_root = tmp_path / "repo"
    site_dir = real_root / ".build" / "i18n" / "ja" / "site"
    site_dir.mkdir(parents=True)
    linked_root = tmp_path / "linked-repo"
    linked_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setattr(build_config, "ROOT", linked_root)

    assert build_config._repo_relative(site_dir, "site directory") == ".build/i18n/ja/site"


def test_repo_relative_rejects_a_path_outside_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(build_config, "ROOT", root)
    elsewhere = tmp_path / "elsewhere"

    with pytest.raises(SystemExit) as failure:
        build_config._repo_relative(elsewhere, "docs directory")

    assert failure.value.code == f"build_config: docs directory {elsewhere} must live inside the repository"


def test_language_config_derives_site_url_switcher_and_api_entry_from_the_given_site_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preview build passes its own host: the language site's `site_url`, the switcher links and the
    API-reference nav entry (a link into the English site) all derive from it, not from `mkdocs.yml`."""
    root = tmp_path / "repo"
    staged = root / ".build" / "i18n" / "ja" / "docs"
    staged.mkdir(parents=True)
    (staged / "index.md").write_text("# Home {#home}\n", encoding="utf-8")
    mkdocs: dict[str, Any] = {
        "site_name": "Docs",
        "site_url": "https://production.example/",
        "nav": ["index.md", {"API Reference": "api/"}],
        "theme": {"name": "material"},
        "plugins": ["search", {"mkdocstrings": {"handlers": {}}}],
    }
    (root / "mkdocs.yml").write_text(yaml.safe_dump(mkdocs, sort_keys=False), encoding="utf-8")

    def japanese_labels(_lang: str) -> dict[str, str]:
        return {"API Reference": "API リファレンス"}

    monkeypatch.setattr(build_config, "ROOT", root)
    monkeypatch.setattr(build_config, "load_registry", lambda: REGISTRY)
    monkeypatch.setattr(build_config, "_translated_labels", japanese_labels)

    output = build_config.build_config(lang="ja", site_url="https://pr-1.docs.pages.dev")

    config: dict[str, Any] = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert config["site_url"] == "https://pr-1.docs.pages.dev/ja/"
    assert config["nav"] == ["index.md", {"API リファレンス": "https://pr-1.docs.pages.dev/api/mcp/"}]
    assert config["extra"]["alternate"] == [ENGLISH, JA_ENTRY, KO_ENTRY]
    assert config["theme"]["language"] == "ja" and config["plugins"] == ["search"]
