"""Tests for the state file and staleness classification (i18n/state.py)."""

from dataclasses import replace
from pathlib import Path

import pytest

from i18n.config import ConfigError
from i18n.state import Fingerprint, LanguageState, PageState, classify, load_state, save_state


def _record(**overrides: str) -> PageState:
    base = PageState(
        source_commit="abc123",
        source_hash="page-hash",
        blocks=("b1", "b2"),
        general_prompt_hash="g",
        instructions_hash="i",
        glossary_hash="l",
        model="model-t",
        translated_at="2026-07-30T00:00:00Z",
    )
    return replace(base, **overrides)


def test_state_round_trips_through_the_file(tmp_path: Path) -> None:
    state = LanguageState(pages={"b.md": _record(), "a.md": _record(model="other")})
    path = tmp_path / "nested" / "state.json"

    save_state(path, state)

    assert load_state(path) == state
    assert path.read_text(encoding="utf-8").index('"a.md"') < path.read_text(encoding="utf-8").index('"b.md"')


def test_load_state_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path / "none.json") == LanguageState()


@pytest.mark.parametrize(
    "document",
    ['{"version": 2, "pages": {}}', '{"version": 1, "pages": {"a.md": {"source_hash": "x"}}}', "not json"],
)
def test_load_state_rejects_off_schema_files(tmp_path: Path, document: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_state(path)


def test_classify_reports_all_four_statuses_with_reasons() -> None:
    fingerprint = _record().fingerprint
    state = LanguageState(
        pages={"current.md": _record(), "edited.md": _record(), "glossary.md": _record(), "gone.md": _record()}
    )
    current = {
        "current.md": fingerprint,
        "edited.md": replace(fingerprint, source_hash="new", blocks=("x",)),
        "glossary.md": replace(fingerprint, glossary_hash="new", blocks=("x",)),
        "missing.md": fingerprint,
    }

    statuses = {s.page: s for s in classify(current, state, translated={"current.md", "edited.md", "glossary.md"})}

    assert statuses["current.md"].status == "current"
    assert statuses["edited.md"].status == "outdated" and statuses["edited.md"].reasons == ("English page changed",)
    assert statuses["glossary.md"].reasons == ("glossary changed",)
    assert statuses["missing.md"].status == "missing"
    assert statuses["gone.md"].status == "removable"


def test_classify_page_with_state_but_no_file_is_missing() -> None:
    fingerprint: Fingerprint = _record().fingerprint

    (status,) = classify({"a.md": fingerprint}, LanguageState(pages={"a.md": _record()}), translated=set())

    assert status.status == "missing"


def test_classify_pipeline_change_is_the_reason_when_only_blocks_differ() -> None:
    fingerprint = replace(_record().fingerprint, blocks=("salt-changed",))

    (status,) = classify({"a.md": fingerprint}, LanguageState(pages={"a.md": _record()}), translated={"a.md"})

    assert status.status == "outdated" and status.reasons == ("translation pipeline changed",)
