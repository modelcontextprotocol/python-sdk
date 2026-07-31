"""The translation registry (`i18n/languages.yml`) and the tool's paths.

The registry is the single list of language sites: the docs build reads it to
know what to build and what the language switcher offers, and this tool reads
it to know what to translate and with which models. Everything path-shaped
about a language (its inputs, generated pages, state file, banner snippets)
derives from its code so a new language is one registry entry plus its
directory.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast, get_args

import yaml

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
I18N_DIR = ROOT / "i18n"
REGISTRY_PATH = I18N_DIR / "languages.yml"
GENERAL_PROMPT_PATH = I18N_DIR / "general-prompt.md"

MODEL_ENV = "MCP_DOCS_I18N_MODEL"
VERIFY_MODEL_ENV = "MCP_DOCS_I18N_VERIFY_MODEL"

BANNER_KINDS = ("disclosure", "outdated", "untranslated", "stale", "english-only")

# The generated map of translated sidebar labels, next to `state.json`.
NAV_FILE = "nav.yml"

# The writing system of a language's prose. The validator keys checks on the
# target's script (e.g. an untranslated-English scan only makes sense for a
# non-Latin target), never on the character mix of the output.
Script = Literal["latin", "cjk", "hangul"]
SCRIPTS: tuple[Script, ...] = get_args(Script)

_CODE = re.compile(r"^[A-Za-z0-9-]+$")
_LANGUAGE_KEYS = {"code", "name", "theme_language", "hreflang", "script", "enabled"}
_TOP_KEYS = {"languages", "exclude_pages", "models"}
_MODEL_KEYS = {"translate", "verify"}


class ConfigError(Exception):
    """A malformed registry, glossary, or missing input file (CLI exit code 2)."""


@dataclass(frozen=True)
class Language:
    """One language site."""

    code: str
    name: str
    theme_language: str
    hreflang: str
    script: Script
    enabled: bool


@dataclass(frozen=True)
class Models:
    """The translation model and the (stronger) semantic-review model."""

    translate: str
    verify: str


@dataclass(frozen=True)
class Registry:
    """The parsed `languages.yml`."""

    languages: tuple[Language, ...]
    exclude_pages: tuple[str, ...]
    models: Models

    @property
    def enabled(self) -> list[Language]:
        """The languages that get a site, in registry order."""
        return [language for language in self.languages if language.enabled]

    def language(self, code: str) -> Language:
        """The registry entry for `code`.

        Raises:
            ConfigError: `code` is not a registered language.
        """
        for language in self.languages:
            if language.code == code:
                return language
        codes = ", ".join(language.code for language in self.languages)
        raise ConfigError(f"unknown language {code!r} (registered: {codes})")


def _keys(section: str, value: object, expected: set[str]) -> Mapping[str, Any]:
    """`value` as a mapping whose keys are exactly `expected`."""
    if not isinstance(value, dict):
        raise ConfigError(f"languages.yml: {section} must be a mapping")
    mapping = cast("dict[str, Any]", value)
    if unknown := sorted(set(mapping) - expected):
        raise ConfigError(f"languages.yml: {section} has unknown keys {unknown}")
    if missing := sorted(expected - set(mapping)):
        raise ConfigError(f"languages.yml: {section} is missing keys {missing}")
    return mapping


def _string(section: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"languages.yml: {section} must be a non-empty string")
    return value


def _strings(section: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in cast("list[object]", value)):
        raise ConfigError(f"languages.yml: {section} must be a list of non-empty strings")
    return tuple(cast("list[str]", value))


def _script(section: str, value: object) -> Script:
    for script in SCRIPTS:
        if value == script:
            return script
    raise ConfigError(f"languages.yml: {section} must be one of {list(SCRIPTS)}, found {value!r}")


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    """Parse and validate the language registry.

    Raises:
        ConfigError: The file is missing or does not match the schema.
    """
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    top = _keys("top level", raw, _TOP_KEYS)

    entries = top["languages"]
    if not isinstance(entries, list) or not entries:
        raise ConfigError("languages.yml: languages must be a non-empty list")
    languages: list[Language] = []
    for entry in cast("list[object]", entries):
        fields = _keys("a languages entry", entry, _LANGUAGE_KEYS)
        code = _string("languages[].code", fields["code"])
        if not _CODE.match(code):
            raise ConfigError(f"languages.yml: language code {code!r} may only use letters, digits and '-'")
        enabled = fields["enabled"]
        if not isinstance(enabled, bool):
            raise ConfigError(f"languages.yml: languages[{code}].enabled must be true or false")
        languages.append(
            Language(
                code=code,
                name=_string(f"languages[{code}].name", fields["name"]),
                theme_language=_string(f"languages[{code}].theme_language", fields["theme_language"]),
                hreflang=_string(f"languages[{code}].hreflang", fields["hreflang"]),
                script=_script(f"languages[{code}].script", fields["script"]),
                enabled=enabled,
            )
        )
    codes = [language.code for language in languages]
    if duplicates := sorted({code for code in codes if codes.count(code) > 1}):
        raise ConfigError(f"languages.yml: duplicate language codes {duplicates}")

    models = _keys("models", top["models"], _MODEL_KEYS)
    return Registry(
        languages=tuple(languages),
        exclude_pages=_strings("exclude_pages", top["exclude_pages"]),
        models=Models(
            translate=_string("models.translate", models["translate"]),
            verify=_string("models.verify", models["verify"]),
        ),
    )


def resolve_models(
    models: Models,
    *,
    environ: Mapping[str, str],
    translate: str | None = None,
    verify: str | None = None,
) -> Models:
    """Apply overrides to the registry's models: CLI flags win over env vars, which win over the file."""
    return replace(
        models,
        translate=translate or environ.get(MODEL_ENV) or models.translate,
        verify=verify or environ.get(VERIFY_MODEL_ENV) or models.verify,
    )


def language_dir(code: str, i18n_dir: Path = I18N_DIR) -> Path:
    """The directory holding one language's inputs and generated pages."""
    return i18n_dir / "languages" / code


def instructions_path(code: str, i18n_dir: Path = I18N_DIR) -> Path:
    return language_dir(code, i18n_dir) / "instructions.md"


def glossary_path(code: str, i18n_dir: Path = I18N_DIR) -> Path:
    return language_dir(code, i18n_dir) / "glossary.json"


def pages_dir(code: str, i18n_dir: Path = I18N_DIR) -> Path:
    """The generated translations, mirroring the page paths under `docs/`."""
    return language_dir(code, i18n_dir) / "pages"


def state_path(code: str, i18n_dir: Path = I18N_DIR) -> Path:
    return language_dir(code, i18n_dir) / "state.json"


def nav_path(code: str, i18n_dir: Path = I18N_DIR) -> Path:
    """The generated translated navigation labels for one language."""
    return language_dir(code, i18n_dir) / NAV_FILE


def general_prompt_path(i18n_dir: Path = I18N_DIR) -> Path:
    return i18n_dir / "general-prompt.md"


def banner_path(kind: str, code: str, i18n_dir: Path = I18N_DIR) -> Path:
    """The banner snippet for `code`, falling back to the English snippet when the language has none."""
    localised = i18n_dir / "banners" / code / f"{kind}.md"
    return localised if localised.is_file() else i18n_dir / "banners" / "en" / f"{kind}.md"


def _build_dir(root: Path) -> Path:
    """The throwaway directory of a repository root holding staged docs trees and language sites."""
    return root / ".build" / "i18n"


def staged_docs_dir(code: str, root: Path) -> Path:
    """Where a language's docs tree is assembled (under repository `root`) before its site is built."""
    return _build_dir(root) / code / "docs"


def staged_site_dir(code: str, root: Path) -> Path:
    """Where a language's site is built (under repository `root`) before being copied into `site/<code>/`."""
    return _build_dir(root) / code / "site"
