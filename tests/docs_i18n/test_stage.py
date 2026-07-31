"""Tests for language-site staging and banner injection (i18n/stage.py)."""

from pathlib import Path

import pytest

from i18n.config import ConfigError
from i18n.stage import (
    StageStatus,
    Withdrawn,
    absolutise_api_links,
    inject_banner,
    missing_document_links,
    stage_language,
    staged_paths,
)
from tests.docs_i18n._repo import Repo, make_repo

INDEX = "# Home {#home}\n\nWelcome.\n"
GUIDE = "# Guide {#guide}\n\nDetails.\n"
ENGLISH_SITE = "https://docs.example"


def _staged(repo: Repo, statuses: dict[str, StageStatus]) -> Path:
    return stage_language(repo.code, statuses, english_site_url=ENGLISH_SITE, root=repo.root).docs


def test_stage_copies_english_overlays_translations_and_banners_each_page(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, nav=("index.md", "guide/deep.md", "translations.md"))
    repo.write_english("index.md", INDEX)
    repo.write_english("guide/deep.md", GUIDE)
    repo.write_english("translations.md", "# Translations {#t}\n")
    (repo.docs / "extra.css").write_text("/* asset */", encoding="utf-8")
    (repo.docs / "api").mkdir()
    (repo.docs / "api" / "gen.md").write_text("generated", encoding="utf-8")
    (repo.docs / ".overrides").mkdir()
    (repo.docs / ".overrides" / "main.html").write_text("theme", encoding="utf-8")
    repo.write_translation("index.md", "# Startseite {#home}\n\nWillkommen.\n")
    repo.write_translation("removed.md", "stale file")

    staged = _staged(repo, {"index.md": "current", "guide/deep.md": "missing", "translations.md": "missing"})

    assert staged == repo.root / ".build" / "i18n" / "xx" / "docs"
    home = (staged / "index.md").read_text(encoding="utf-8")
    assert home.startswith('# Startseite {#home}\n\n??? info "Machine-translated"\n')
    assert "English original: https://docs.example/. Report: translations.md." in home
    assert home.rstrip("\n").endswith("Willkommen.")
    deep = (staged / "guide" / "deep.md").read_text(encoding="utf-8")
    assert '!!! note "Not yet"' in deep and "See ../translations.md." in deep and "Details." in deep
    assert (staged / "extra.css").is_file()
    assert not (staged / "api").exists() and not (staged / ".overrides").exists()
    assert not (staged / "removed.md").exists()


def test_stage_outdated_page_gets_disclosure_and_outdated_banners(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, nav=("index.md",))
    repo.write_english("index.md", INDEX)
    repo.write_translation("index.md", "# Startseite {#home}\n\nAlt.\n")

    staged = _staged(repo, {"index.md": "outdated"})

    home = (staged / "index.md").read_text(encoding="utf-8")
    assert home.index('??? info "Machine-translated"') < home.index('!!! warning "Behind"') < home.index("Alt.")
    assert "See https://docs.example/." in home


def test_stage_excluded_page_keeps_english_with_the_english_only_banner(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, nav=("index.md", "migration.md"))
    repo.write_english("index.md", INDEX)
    repo.write_english("migration.md", "# Migration {#m}\n\nEnglish body.\n")

    staged = _staged(repo, {"index.md": "missing", "migration.md": "excluded"})

    migration = (staged / "migration.md").read_text(encoding="utf-8")
    assert '!!! note "English only"' in migration and "English body." in migration
    assert '!!! note "Not yet"' not in migration
    assert '!!! note "Not yet"' in (staged / "index.md").read_text(encoding="utf-8")


def test_stage_withdraws_a_translation_linking_a_page_the_english_tree_dropped(tmp_path: Path) -> None:
    """An English rename leaves the translation linking the old page: staging keeps the English page,
    marked as being refreshed, so the language build never sees the dead link."""
    repo = make_repo(tmp_path, nav=("index.md", "new.md", "translations.md"))
    repo.write_english("index.md", "# Home {#home}\n\nRead the [new page](new.md).\n")
    repo.write_english("new.md", "# New {#new}\n")
    repo.write_english("translations.md", "# Translations {#t}\n")
    # Translated back when the target was still old.md, which the rename removed.
    repo.write_translation("index.md", "# Startseite {#home}\n\nLies die [alte Seite](old.md).\n")

    result = stage_language(
        repo.code,
        {"index.md": "outdated", "new.md": "missing", "translations.md": "missing"},
        english_site_url=ENGLISH_SITE,
        root=repo.root,
    )

    assert result.withdrawn == [Withdrawn("index.md", ("old.md",))]
    home = (result.docs / "index.md").read_text(encoding="utf-8")
    assert home.startswith('# Home {#home}\n\n!!! warning "Being refreshed"\n')
    assert "Read the [new page](new.md)." in home and "alte Seite" not in home


def test_stage_keeps_a_translation_whose_dead_link_the_english_page_writes_too(tmp_path: Path) -> None:
    """A dead link the English page also carries is the English tree's own defect (its strict build catches
    it), never grounds to withdraw the translation for copying it."""
    repo = make_repo(tmp_path, nav=("index.md",))
    repo.write_english("index.md", "# Home {#home}\n\nSee [prompts](prompts.md).\n")
    repo.write_translation("index.md", "# Startseite {#home}\n\nZeu [Prompten](prompts.md).\n")

    result = stage_language(repo.code, {"index.md": "current"}, english_site_url=ENGLISH_SITE, root=repo.root)

    assert result.withdrawn == []
    assert "Zeu [Prompten](prompts.md)." in (result.docs / "index.md").read_text(encoding="utf-8")


# Each case: the link target as written on index.md, the tree's paths, and the missing docs paths reported.
LINK_CASES: list[tuple[str, set[str], list[str]]] = [
    ("prompts.md", {"prompts.md"}, []),
    ("guide/deep.md#anchor", {"guide", "guide/deep.md"}, []),
    ("../escapes.md", set(), ["../escapes.md"]),
    ("missing.md#x", {"index.md"}, ["missing.md"]),
    ("sub/", {"sub", "sub/index.md"}, []),
    ("img/shot.png", set(), ["img/shot.png"]),
    ("#in-page", set(), []),
    ("https://example.org/gone.md", set(), []),
    ("api/mcp/index.md", set(), []),
    ("/absolute/page/", set(), []),
]


@pytest.mark.parametrize(("target", "present", "missing"), LINK_CASES)
def test_missing_document_links_reports_the_docs_paths_relative_targets_reach_for_but_the_tree_lacks(
    target: str, present: set[str], missing: list[str]
) -> None:
    assert missing_document_links(f"See [it]({target}).", "index.md", present) == missing


def test_staged_paths_are_the_english_tree_without_the_api_reference_and_dot_entries(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    for path in ("index.md", "guide/deep.md", "img/a.png", "api/gen.md", ".overrides/main.html"):
        (docs / path).parent.mkdir(parents=True, exist_ok=True)
        (docs / path).write_text("x", encoding="utf-8")

    assert staged_paths(docs) == {"index.md", "guide", "guide/deep.md", "img", "img/a.png"}


def test_stage_refuses_a_target_outside_the_build_directory(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, nav=("index.md",))
    repo.write_english("index.md", INDEX)

    with pytest.raises(ConfigError) as failure:
        stage_language("../..", {"index.md": "missing"}, english_site_url=ENGLISH_SITE, root=repo.root)

    assert "refusing to stage into" in str(failure.value)
    assert (repo.docs / "index.md").is_file()


def test_stage_points_a_pages_api_reference_link_at_the_english_site(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, nav=("index.md",))
    repo.write_english("index.md", "# Home {#home}\n\nSee the [API Reference](api/mcp/index.md).\n")
    translation = "# Startseite {#home}\n\nSieh die [API-Referenz](api/mcp/index.md).\n"
    repo.write_translation("index.md", translation)

    staged = _staged(repo, {"index.md": "current"})

    assert f"[API-Referenz]({ENGLISH_SITE}/api/mcp/)" in (staged / "index.md").read_text(encoding="utf-8")
    # The committed translation keeps the English link so the parity check still passes.
    assert (repo.pages / "index.md").read_text(encoding="utf-8") == translation


def test_absolutise_api_links_resolves_targets_from_the_page_directory_and_keeps_fragments() -> None:
    text = "[deep](../api/mcp/server/index.md#run) [dir](../api/mcp/) [asset](../api/mcp/objects.inv)"

    rewritten = absolutise_api_links(text, "guide/deep.md", english_site_url=f"{ENGLISH_SITE}/")

    assert rewritten == (
        f"[deep]({ENGLISH_SITE}/api/mcp/server/#run) [dir]({ENGLISH_SITE}/api/mcp/) "
        f"[asset]({ENGLISH_SITE}/api/mcp/objects.inv)"
    )


def test_absolutise_api_links_leaves_non_api_targets_and_code_untouched() -> None:
    text = (
        "[page](../servers/tools.md) [anchor](#home) [image](../img/api/logo.png) "
        f"[external]({ENGLISH_SITE}/api/mcp/) [absolute](/api/mcp/) "
        "`[code](api/mcp/index.md)`\n\n```\n[fenced](api/mcp/index.md)\n```\n"
    )

    assert absolutise_api_links(text, "servers/tools.md", english_site_url=ENGLISH_SITE) == text


def test_stage_prefers_language_banners_over_the_english_fallback(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, nav=("index.md",))
    repo.write_english("index.md", INDEX)
    banners = repo.i18n / "banners" / repo.code
    banners.mkdir(parents=True)
    (banners / "untranslated.md").write_text('!!! note "Noch nicht"\n    Original zeigt sich.\n', encoding="utf-8")

    staged = _staged(repo, {"index.md": "missing"})

    assert '!!! note "Noch nicht"' in (staged / "index.md").read_text(encoding="utf-8")


def test_inject_banner_prepends_when_the_page_has_no_title() -> None:
    assert inject_banner("No heading here.\n", "BANNER") == "BANNER\n\nNo heading here.\n"


def test_inject_banner_keeps_leading_front_matter_first_on_a_titleless_page() -> None:
    page = "---\ntitle: Tools\n---\n\nNo heading here.\n"

    assert inject_banner(page, "BANNER") == "---\ntitle: Tools\n---\n\nBANNER\n\nNo heading here.\n"
