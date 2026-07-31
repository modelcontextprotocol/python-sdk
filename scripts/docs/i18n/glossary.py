"""A language's `glossary.json`: schema, loading and the fingerprint it feeds.

The glossary is the machine-checkable half of a language's rules. It rides
along in every prompt, and the validator enforces two of its lists after the
fact: terms that must stay in English appear verbatim, and banned renderings
never appear. The schema is closed — a misspelt key is an error, not a
silently ignored field.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from i18n.config import ConfigError

SCHEMA_VERSION = 1
_TOP_KEYS = {"version", "keep_in_source_language", "terms"}
_TERM_KEYS = {"source", "target", "note", "avoid", "enforce"}
_REQUIRED_TERM_KEYS = {"source", "target"}


@dataclass(frozen=True)
class Term:
    """A required rendering (`target`) and banned renderings (`avoid`) for one English term."""

    source: str
    target: str
    note: str = ""
    avoid: tuple[str, ...] = field(default_factory=tuple)
    enforce: bool = False


@dataclass(frozen=True)
class Glossary:
    keep_in_source_language: tuple[str, ...]
    terms: tuple[Term, ...]

    @property
    def enforced_avoids(self) -> list[tuple[str, str]]:
        """Every `(source, banned rendering)` pair the validator must reject."""
        return [(term.source, avoid) for term in self.terms if term.enforce for avoid in term.avoid]


def _fail(path: Path, message: str) -> ConfigError:
    return ConfigError(f"{path}: {message}")


def _keys(path: Path, section: str, value: object, allowed: set[str], required: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _fail(path, f"{section} must be an object")
    mapping = cast("dict[str, Any]", value)
    if unknown := sorted(set(mapping) - allowed):
        raise _fail(path, f"{section} has unknown keys {unknown}")
    if missing := sorted(required - set(mapping)):
        raise _fail(path, f"{section} is missing keys {missing}")
    return mapping


def _strings(path: Path, section: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in cast("list[object]", value)):
        raise _fail(path, f"{section} must be a list of non-empty strings")
    return tuple(cast("list[str]", value))


def load_glossary(path: Path) -> Glossary:
    """Parse and validate a glossary file.

    Raises:
        ConfigError: The file is missing, malformed, or off-schema.
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _fail(path, f"cannot read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise _fail(path, f"invalid JSON: {exc}") from exc

    top = _keys(path, "top level", raw, _TOP_KEYS, _TOP_KEYS)
    if top["version"] != SCHEMA_VERSION:
        raise _fail(path, f"version must be {SCHEMA_VERSION}")
    keep = _strings(path, "keep_in_source_language", top["keep_in_source_language"])
    entries = top["terms"]
    if not isinstance(entries, list):
        raise _fail(path, "terms must be a list")

    terms: list[Term] = []
    for index, entry in enumerate(cast("list[object]", entries)):
        fields = _keys(path, f"terms[{index}]", entry, _TERM_KEYS, _REQUIRED_TERM_KEYS)
        source, target, note = fields["source"], fields["target"], fields.get("note", "")
        if not all(isinstance(value, str) for value in (source, target, note)) or not source or not target:
            raise _fail(path, f"terms[{index}]: source, target and note must be strings")
        avoid = _strings(path, f"terms[{index}].avoid", fields.get("avoid", []))
        enforce = fields.get("enforce", False)
        if not isinstance(enforce, bool):
            raise _fail(path, f"terms[{index}].enforce must be true or false")
        terms.append(Term(source=source, target=target, note=note, avoid=avoid, enforce=enforce))

    return Glossary(keep_in_source_language=keep, terms=tuple(terms))


def glossary_prompt(glossary: Glossary) -> str:
    """The glossary rendered as the prompt section the model sees."""
    lines = ["## Glossary", "", "These terms always stay in English, spelled exactly like this:", ""]
    lines += [f"- {term}" for term in glossary.keep_in_source_language]
    if glossary.terms:
        lines += ["", "Use these renderings; the notes are binding:", ""]
    for term in glossary.terms:
        entry = f"- {term.source} → {term.target}"
        if term.avoid:
            entry += f" (never: {', '.join(term.avoid)})"
        if term.note:
            entry += f". {term.note}"
        lines.append(entry)
    lines.append("")
    return "\n".join(lines)
