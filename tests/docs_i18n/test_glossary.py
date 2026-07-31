"""Tests for glossary loading and rendering (i18n/glossary.py)."""

import json
from pathlib import Path

import pytest

from i18n.config import ConfigError
from i18n.glossary import Glossary, Term, glossary_prompt, load_glossary


def _write(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_glossary_parses_terms_with_defaults(tmp_path: Path) -> None:
    document = {
        "version": 1,
        "keep_in_source_language": ["MCP"],
        "terms": [
            {"source": "tool", "target": "工具", "note": "n", "avoid": ["用具"], "enforce": True},
            {"source": "prompt", "target": "提示词"},
        ],
    }

    glossary = load_glossary(_write(tmp_path, document))

    assert glossary.keep_in_source_language == ("MCP",)
    assert glossary.terms == (
        Term("tool", "工具", "n", ("用具",), True),
        Term("prompt", "提示词", "", (), False),
    )
    assert glossary.enforced_avoids == [("tool", "用具")]


@pytest.mark.parametrize(
    ("document", "problem"),
    [
        (
            {"version": 1, "keep_in_source_language": [], "terms": [], "extra": 1},
            "top level has unknown keys ['extra']",
        ),
        ({"version": 2, "keep_in_source_language": [], "terms": []}, "version must be 1"),
        (
            {"version": 1, "keep_in_source_language": [""], "terms": []},
            "keep_in_source_language must be a list of non-empty strings",
        ),
        (
            {"version": 1, "keep_in_source_language": [], "terms": [{"source": "a"}]},
            "terms[0] is missing keys ['target']",
        ),
        (
            {"version": 1, "keep_in_source_language": [], "terms": [{"source": "a", "target": "b", "x": 1}]},
            "terms[0] has unknown keys ['x']",
        ),
        (
            {"version": 1, "keep_in_source_language": [], "terms": [{"source": "a", "target": "b", "enforce": "y"}]},
            "terms[0].enforce must be true or false",
        ),
        ({"version": 1, "keep_in_source_language": [], "terms": "no"}, "terms must be a list"),
    ],
)
def test_load_glossary_rejects_off_schema_files(tmp_path: Path, document: object, problem: str) -> None:
    path = _write(tmp_path, document)

    with pytest.raises(ConfigError) as failure:
        load_glossary(path)

    assert str(failure.value) == f"{path}: {problem}"


def test_load_glossary_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "glossary.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError) as failure:
        load_glossary(path)

    # Our prefix is pinned; the tail is the JSON parser's own text, which is not.
    assert str(failure.value).startswith(f"{path}: invalid JSON: ")


def test_glossary_prompt_lists_keep_terms_targets_avoids_and_notes() -> None:
    glossary = Glossary(("MCP", "stdio"), (Term("tool", "工具", "protocol noun", ("用具",), True),))

    prompt = glossary_prompt(glossary)

    assert prompt.index("- MCP") < prompt.index("- stdio") < prompt.index("- tool → 工具")
    assert "never: 用具" in prompt and "protocol noun" in prompt
