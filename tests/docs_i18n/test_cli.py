"""Tests for the command line (i18n/cli.py): commands, output and exit codes, with no network."""

import json
from pathlib import Path
from typing import Any

import pytest

from i18n.cli import EXIT_FAILURES, EXIT_OK, EXIT_USAGE, main
from i18n.nav import load_nav
from tests.docs_i18n._repo import (
    ENGLISH,
    SITE_NAME,
    TRANSLATED,
    FakeTranslator,
    Repo,
    make_repo,
    nav_reply,
    write_glossary,
)


def _run(repo: Repo, *argv: str, translator: FakeTranslator | None = None) -> int:
    return main(["--repo-root", str(repo.root), *argv], translator=translator, environ={})


@pytest.fixture
def docs_repo(tmp_path: Path) -> Repo:
    repo = make_repo(tmp_path, nav=("index.md", "tools.md", "translations.md", "migration.md"))
    repo.write_english("index.md", "# Home {#home}\n\nWelcome to MCP.\n")
    repo.write_english("tools.md", ENGLISH)
    repo.write_english("translations.md", "# Translations {#t}\n")
    repo.write_english("migration.md", "# Migration {#m}\n")
    return repo


def test_status_lists_missing_pages_and_hides_excluded_ones(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(docs_repo, "status") == EXIT_OK

    out = capsys.readouterr().out
    assert "xx (Testish): 3 missing, 0 outdated, 0 current, 0 removable" in out
    assert "  missing   tools.md" in out
    assert "migration.md" not in out


def test_languages_prints_enabled_codes(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(docs_repo, "languages") == EXIT_OK
    assert capsys.readouterr().out.strip() == "xx"


def test_translate_dry_run_prints_the_prompt_without_a_model(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(docs_repo, "translate", "--lang", "xx", "--pages", "tools.md", "--dry-run") == EXIT_OK

    out = capsys.readouterr().out
    assert "tools.md (whole page, model model-t)" in out
    assert "General rules." in out and "Testish rules." in out and ENGLISH in out
    assert not docs_repo.pages.exists()


def test_translate_writes_pages_and_state_then_reports_current(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    home = "# Startseite {#home}\n\nWillkommen bei MCP.\n"
    fake = FakeTranslator([home, TRANSLATED])

    assert (
        _run(docs_repo, "translate", "--lang", "xx", "--all-missing", "--no-verify", "--limit", "2", translator=fake)
        == EXIT_OK
    )

    assert (docs_repo.pages / "index.md").read_text(encoding="utf-8") == home
    assert (docs_repo.pages / "tools.md").read_text(encoding="utf-8") == TRANSLATED
    state = json.loads(docs_repo.state_path.read_text(encoding="utf-8"))
    assert set(state["pages"]) == {"index.md", "tools.md"} and state["pages"]["index.md"]["model"] == "model-t"
    capsys.readouterr()
    assert _run(docs_repo, "status", "--lang", "xx") == EXIT_OK
    assert "1 missing, 0 outdated, 2 current, 0 removable" in capsys.readouterr().out


def test_translate_failure_reports_findings_and_exits_1(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    broken = "# Nur Titel {#tools}\n"
    fake = FakeTranslator([broken, broken, broken])

    exit_code = _run(docs_repo, "translate", "--lang", "xx", "--pages", "tools.md", "--no-verify", translator=fake)

    assert exit_code == EXIT_FAILURES
    assert "error: tools.md failed" in capsys.readouterr().err
    assert not (docs_repo.pages / "tools.md").exists()


@pytest.mark.parametrize("limit", ["0", "-2", "many"])
def test_translate_limit_must_be_a_positive_number(docs_repo: Repo, limit: str) -> None:
    with pytest.raises(SystemExit) as failure:
        _run(docs_repo, "translate", "--lang", "xx", "--all-missing", "--limit", limit)

    assert failure.value.code == EXIT_USAGE


def test_translate_without_selection_or_credentials_is_a_usage_error(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(docs_repo, "translate", "--lang", "xx") == EXIT_USAGE
    assert "nothing selected" in capsys.readouterr().err

    assert _run(docs_repo, "translate", "--lang", "xx", "--all-missing") == EXIT_USAGE
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err

    assert _run(docs_repo, "translate", "--lang", "xx", "--pages", "nope.md") == EXIT_USAGE
    assert "not translatable" in capsys.readouterr().err


def _translate_tools(repo: Repo) -> None:
    """Give `tools.md` a real, current translation: the tool writes the page and its state record."""
    fake = FakeTranslator([TRANSLATED])
    assert _run(repo, "translate", "--lang", "xx", "--pages", "tools.md", "--no-verify", translator=fake) == EXIT_OK


def test_check_validates_a_current_page_against_its_english_source(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _translate_tools(docs_repo)
    assert _run(docs_repo, "check") == EXIT_OK
    assert "translated pages are valid" in capsys.readouterr().out

    # A hand-edit that breaks the page's parity with the English source fails the gate.
    docs_repo.write_translation("tools.md", TRANSLATED.replace("(prompts.md)", "(wrong.md)"))
    assert _run(docs_repo, "check", "--lang", "xx", "--pages", "tools.md") == EXIT_FAILURES
    assert "missing link targets" in capsys.readouterr().err


def test_check_reports_an_outdated_page_without_failing_even_when_the_english_has_diverged(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _translate_tools(docs_repo)
    # The English page grows a section: the translation is now behind it and
    # structurally divergent from it, which is staleness, never a broken page.
    docs_repo.write_english("tools.md", ENGLISH + "\n## Advanced usage {#advanced-usage}\n\nMore.\n")

    assert _run(docs_repo, "check") == EXIT_OK
    out = capsys.readouterr().out
    assert "note: xx: outdated (1 page) — refreshed by the next translation run: tools.md" in out
    assert "translated pages are valid" in out


def test_check_still_fails_an_outdated_page_that_is_broken_on_its_own(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _translate_tools(docs_repo)
    docs_repo.write_english("tools.md", ENGLISH + "\n## Advanced usage {#advanced-usage}\n\nMore.\n")
    # An outdated page is not compared with the new English, but it must still be well-formed itself.
    docs_repo.write_translation("tools.md", TRANSLATED.replace("```\n\nXx `Context`", "\nXx `Context`"))

    assert _run(docs_repo, "check") == EXIT_FAILURES
    assert "code block 1 is not closed" in capsys.readouterr().err


def test_check_reports_a_translation_whose_english_page_was_deleted_and_does_not_read_it(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _translate_tools(docs_repo)
    (docs_repo.docs / "tools.md").unlink()
    (docs_repo.root / "mkdocs.yml").write_text(
        "site_name: Test docs\nsite_url: https://docs.example/\nnav:\n  - index.md\n  - translations.md\n"
        "  - migration.md\n",
        encoding="utf-8",
    )

    assert _run(docs_repo, "check") == EXIT_OK
    assert "note: xx: removable (1 page) — gone from docs/; run `prune --lang xx`: tools.md" in (
        capsys.readouterr().out
    )


def test_check_reports_an_untracked_translation_file_that_has_no_state_record(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    # A page committed by hand, with no state.json record: not published, not compared, only reported.
    docs_repo.write_translation("tools.md", TRANSLATED.replace("(prompts.md)", "(wrong.md)"))

    assert _run(docs_repo, "check") == EXIT_OK
    assert "note: xx: untracked (1 page)" in capsys.readouterr().out


def test_check_rejects_a_bad_glossary_as_a_config_error(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    (docs_repo.i18n / "languages" / "xx" / "glossary.json").write_text('{"version": 9}', encoding="utf-8")

    assert _run(docs_repo, "check") == EXIT_USAGE
    assert "glossary.json" in capsys.readouterr().err


def test_verify_reviews_a_page_and_fails_on_a_blocker(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    docs_repo.write_translation("index.md", "# Startseite {#home}\n\nMCP ist nicht willkommen.\n")
    blocker = json.dumps(
        [
            {
                "severity": "blocker",
                "source_quote": "Welcome to MCP",
                "target_quote": "MCP ist nicht willkommen",
                "explanation": "inverted",
            }
        ]
    )

    exit_code = _run(docs_repo, "verify", "--lang", "xx", "--pages", "index.md", translator=FakeTranslator([blocker]))

    assert exit_code == EXIT_FAILURES
    captured = capsys.readouterr()
    assert "[blocker]" in captured.err and "1 page(s) reviewed with model-v" in captured.out


def test_verify_of_a_structurally_broken_page_fails_without_reviewing(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    docs_repo.write_translation("index.md", "kein Titel\n")

    exit_code = _run(docs_repo, "verify", "--lang", "xx", "--pages", "index.md", translator=FakeTranslator([]))

    assert exit_code == EXIT_FAILURES
    assert "not structurally valid" in capsys.readouterr().err


def test_prune_deletes_removable_and_stray_files(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeTranslator([TRANSLATED])
    assert (
        _run(docs_repo, "translate", "--lang", "xx", "--pages", "tools.md", "--no-verify", translator=fake) == EXIT_OK
    )
    (docs_repo.docs / "tools.md").unlink()
    (docs_repo.root / "mkdocs.yml").write_text(
        "site_name: T\nsite_url: https://docs.example/\nnav:\n  - index.md\n", encoding="utf-8"
    )
    docs_repo.write_translation("stray.md", "orphan")

    assert _run(docs_repo, "prune", "--lang", "xx") == EXIT_OK

    assert not (docs_repo.pages / "tools.md").exists() and not (docs_repo.pages / "stray.md").exists()
    assert json.loads(docs_repo.state_path.read_text(encoding="utf-8"))["pages"] == {}
    assert "pruned: tools.md" in capsys.readouterr().out


def test_stage_command_builds_the_tree_under_the_repo_root_with_untranslated_banners(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(docs_repo, "stage", "--lang", "xx") == EXIT_OK

    # The staged tree lands under the --repo-root the command was given, not this checkout's.
    staged = docs_repo.root / ".build" / "i18n" / "xx" / "docs"
    assert f"staged xx docs at {staged}" in capsys.readouterr().out
    assert '!!! note "Not yet"' in (staged / "index.md").read_text(encoding="utf-8")
    # Excluded pages are staged as English, marked "available in English only".
    assert '!!! note "English only"' in (staged / "migration.md").read_text(encoding="utf-8")


@pytest.fixture
def rename_repo(tmp_path: Path) -> Repo:
    """A repo whose translated `about.md` links `guide.md`, so an English rename of that page strands it."""
    repo = make_repo(tmp_path, nav=("index.md", "about.md", "guide.md", "translations.md"))
    repo.write_english("index.md", "# Home {#home}\n")
    repo.write_english("about.md", "# About {#about}\n\nStart with [the guide](guide.md).\n")
    repo.write_english("guide.md", "# Guide {#guide}\n")
    repo.write_english("translations.md", "# Translations {#t}\n")
    fake = FakeTranslator(["# Ueber {#about}\n\nBeginne mit [der Anleitung](guide.md).\n"])
    assert _run(repo, "translate", "--lang", "xx", "--pages", "about.md", "--no-verify", translator=fake) == EXIT_OK
    return repo


def _rename_guide_page(repo: Repo) -> None:
    """The English change: `guide.md` becomes `manual.md`, with the nav and every English link following it."""
    (repo.docs / "guide.md").rename(repo.docs / "manual.md")
    repo.write_english("about.md", "# About {#about}\n\nStart with [the guide](manual.md).\n")
    config = (repo.root / "mkdocs.yml").read_text(encoding="utf-8").replace("guide.md", "manual.md")
    (repo.root / "mkdocs.yml").write_text(config, encoding="utf-8")


def test_english_rename_stranding_a_translation_never_fails_check_and_stages_english_with_the_stale_banner(
    rename_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    """Steps: rename the English page the translation links to; `status` names the page outdated with the
    reason its links broke; `check` still passes; `stage` warns, keeps the English page and marks it stale."""
    _rename_guide_page(rename_repo)

    assert _run(rename_repo, "status") == EXIT_OK
    out = capsys.readouterr().out
    assert (
        "  outdated  about.md  (English page changed; links broken by an English change"
        " — English shown until refreshed)" in out
    )

    assert _run(rename_repo, "check") == EXIT_OK
    assert "note: xx: outdated (1 page) — refreshed by the next translation run: about.md" in (capsys.readouterr().out)

    assert _run(rename_repo, "stage", "--lang", "xx") == EXIT_OK
    captured = capsys.readouterr()
    assert "warning: xx: about.md not published — its translation links guide.md," in captured.err
    about = (rename_repo.root / ".build" / "i18n" / "xx" / "docs" / "about.md").read_text(encoding="utf-8")
    assert about.startswith('# About {#about}\n\n!!! warning "Being refreshed"\n')
    assert "Start with [the guide](manual.md)." in about and "Anleitung" not in about


def test_check_never_fails_a_page_that_a_glossary_edit_made_outdated(
    docs_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    """A newly enforced `avoid` term is exactly why the page is outdated; enforcing it offline would fail CI
    until a fresh translation run lands, so `check` only reports the page for that run."""
    _translate_tools(docs_repo)
    # `naam` appears in the translated page; the maintainer now bans it as the rendering of "name".
    banned_naam: dict[str, object] = {
        "version": 1,
        "keep_in_source_language": ["MCP", "Context"],
        "terms": [{"source": "name", "target": "Name", "avoid": ["naam"], "enforce": True}],
    }
    write_glossary(docs_repo, banned_naam)

    assert _run(docs_repo, "check") == EXIT_OK
    out = capsys.readouterr().out
    assert "note: xx: outdated (1 page) — refreshed by the next translation run: tools.md" in out
    assert "translated pages are valid" in out


def test_missing_languages_registry_is_a_config_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path)
    (repo.i18n / "languages.yml").unlink()

    assert main(["--repo-root", str(repo.root), "status"], environ={}) == EXIT_USAGE
    assert "cannot read" in capsys.readouterr().err


def test_unknown_language_is_a_config_error(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(docs_repo, "status", "--lang", "zz") == EXIT_USAGE
    assert "unknown language 'zz'" in capsys.readouterr().err


@pytest.fixture
def nav_repo(tmp_path: Path) -> Repo:
    """A repo whose mkdocs nav carries translatable labels: a section, an explicit label, an external link."""
    nav: list[Any] = [
        {SITE_NAME: "index.md"},
        {"Get started": ["tools.md", {"The Context": "context.md"}]},
        {"Blog": "https://example.org/blog"},
        "translations.md",
    ]
    repo = make_repo(tmp_path, nav=nav)
    repo.write_english("index.md", "# Home {#home}\n\nWelcome to MCP.\n")
    repo.write_english("tools.md", ENGLISH)
    repo.write_english("context.md", "# The Context {#context}\n\nThe Context object.\n")
    repo.write_english("translations.md", "# Translations {#t}\n")
    return repo


def test_status_reports_the_nav_map_missing_then_current_then_outdated(
    nav_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(nav_repo, "status") == EXIT_OK
    assert "  missing   nav.yml (navigation labels)" in capsys.readouterr().out

    labels = {"Get started": "Los geht's", "The Context": "Der Context", "Blog": "Blog"}
    assert (
        _run(nav_repo, "translate", "--lang", "xx", "--nav", translator=FakeTranslator([nav_reply(labels)])) == EXIT_OK
    )
    capsys.readouterr()
    assert _run(nav_repo, "status") == EXIT_OK
    assert "  current   nav.yml (navigation labels)" in capsys.readouterr().out

    # An edited nav label in mkdocs.yml, then a glossary edit, each mark it outdated.
    config = (nav_repo.root / "mkdocs.yml").read_text(encoding="utf-8").replace("Get started", "Get going")
    (nav_repo.root / "mkdocs.yml").write_text(config, encoding="utf-8")
    assert _run(nav_repo, "status") == EXIT_OK
    assert "  outdated  nav.yml (navigation labels)  (nav labels changed)" in capsys.readouterr().out

    write_glossary(nav_repo, {"version": 1, "keep_in_source_language": ["MCP"], "terms": []})
    assert _run(nav_repo, "status") == EXIT_OK
    assert "(nav labels changed; glossary changed)" in capsys.readouterr().out


def test_translate_nav_writes_the_map_and_all_missing_includes_it(
    nav_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    labels = {"Get started": "Los geht's", "The Context": "Der Context", "Blog": "Blog"}
    home = "# Startseite {#home}\n\nWillkommen bei MCP.\n"
    context = "# Der Context {#context}\n\nDas Context-Objekt.\n"
    # The nav map is written first, then the missing pages in nav order.
    fake = FakeTranslator([nav_reply(labels), home, TRANSLATED, context, "# Uebersetzungen {#t}\n"])

    assert _run(nav_repo, "translate", "--lang", "xx", "--all-missing", "--no-verify", translator=fake) == EXIT_OK

    nav = load_nav(nav_repo.nav_path)
    assert nav is not None and nav.labels == labels and nav.state.model == "model-t"
    out = capsys.readouterr().out
    assert "translated: nav.yml (3 labels)" in out and "translated: index.md" in out
    assert not fake.replies


def test_translate_nav_dry_run_prints_the_label_prompt_without_a_model(
    nav_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(nav_repo, "translate", "--lang", "xx", "--nav", "--dry-run") == EXIT_OK

    out = capsys.readouterr().out
    assert "===== nav.yml (navigation labels) (whole map, model model-t) =====" in out
    assert "General rules." in out and "Testish rules." in out
    assert "1. Get started\n2. The Context\n3. Blog" in out
    assert not nav_repo.nav_path.exists()


def test_translate_nav_failure_reports_findings_and_exits_1(nav_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    broken = nav_reply({"Get started": "Los geht's"})
    fake = FakeTranslator([broken, broken, broken])

    assert _run(nav_repo, "translate", "--lang", "xx", "--nav", translator=fake) == EXIT_FAILURES

    err = capsys.readouterr().err
    assert "error: nav.yml failed" in err and "missing renderings" in err
    assert not nav_repo.nav_path.exists()


def test_check_validates_the_nav_map_and_notes_stale_entries(
    nav_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    labels = {"Get started": "Los geht's", "The Context": "Der Context", "Blog": "Blog"}
    assert (
        _run(nav_repo, "translate", "--lang", "xx", "--nav", translator=FakeTranslator([nav_reply(labels)])) == EXIT_OK
    )
    capsys.readouterr()
    # The nav drops the external link: its rendering lingers in the map as a stale entry.
    config = (nav_repo.root / "mkdocs.yml").read_text(encoding="utf-8")
    (nav_repo.root / "mkdocs.yml").write_text(
        config.replace("- Blog: https://example.org/blog\n", ""), encoding="utf-8"
    )

    assert _run(nav_repo, "check") == EXIT_OK
    out = capsys.readouterr().out
    assert "stale entries no longer in mkdocs.yml: ['Blog']" in out
    assert "nav maps and translated pages are valid" in out

    nav_repo.nav_path.write_text(nav_repo.nav_path.read_text(encoding="utf-8").replace("Der Context", "Der Kontext"))
    assert _run(nav_repo, "check") == EXIT_FAILURES
    assert "'Context' must appear verbatim" in capsys.readouterr().err


def test_check_rejects_an_off_schema_nav_map_as_a_config_error(
    nav_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    nav_repo.nav_path.write_text("version: 1\nlabels: {}\nsurprise: 1\n", encoding="utf-8")

    assert _run(nav_repo, "check") == EXIT_USAGE
    assert "nav.yml" in capsys.readouterr().err


def test_translate_nav_without_labels_is_a_usage_error(docs_repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(docs_repo, "translate", "--lang", "xx", "--nav") == EXIT_USAGE
    assert "no translatable navigation labels" in capsys.readouterr().err
