"""A language's `state.json` and the staleness classification built on it.

The state records what every translated page was made from: the English
commit and page hash, the per-block hashes, and the fingerprints of the
three prompt inputs. A translation is current only while all of those still
match the working tree, so an English edit, a glossary tweak or a rewritten
style guide each surface as `outdated` on exactly the pages they affect.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from i18n.config import ConfigError
from i18n.files import write_text_atomically

SCHEMA_VERSION = 1
Status = Literal["missing", "outdated", "current", "removable"]


@dataclass(frozen=True)
class Fingerprint:
    """Everything a translation depends on; equality means the translation is still current."""

    source_hash: str
    blocks: tuple[str, ...]
    general_prompt_hash: str
    instructions_hash: str
    glossary_hash: str


@dataclass(frozen=True)
class PageState:
    """What one page's translation was generated from."""

    source_commit: str
    source_hash: str
    blocks: tuple[str, ...]
    general_prompt_hash: str
    instructions_hash: str
    glossary_hash: str
    model: str
    translated_at: str

    @property
    def fingerprint(self) -> Fingerprint:
        return Fingerprint(
            source_hash=self.source_hash,
            blocks=self.blocks,
            general_prompt_hash=self.general_prompt_hash,
            instructions_hash=self.instructions_hash,
            glossary_hash=self.glossary_hash,
        )


@dataclass
class LanguageState:
    """All of one language's page records, keyed by docs-relative path."""

    pages: dict[str, PageState] = field(default_factory=dict[str, PageState])


@dataclass(frozen=True)
class PageStatus:
    """The classification of one page for one language."""

    page: str
    status: Status
    reasons: tuple[str, ...] = ()


_FIELDS = tuple(PageState.__dataclass_fields__)


def load_state(path: Path) -> LanguageState:
    """Read a state file; a missing file is an empty state.

    Raises:
        ConfigError: The file exists but is unreadable or off-schema.
    """
    if not path.is_file():
        return LanguageState()
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read state: {exc}") from exc
    document = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    records = document.get("pages")
    if document.get("version") != SCHEMA_VERSION or not isinstance(records, dict):
        raise ConfigError(f"{path}: not a version {SCHEMA_VERSION} state file")
    pages: dict[str, PageState] = {}
    for page, record in cast("dict[str, Any]", records).items():
        pages[page] = _page_state(path, page, record)
    return LanguageState(pages=pages)


def _page_state(path: Path, page: str, record: object) -> PageState:
    """One page's record, validated against the `PageState` fields."""
    if not isinstance(record, dict) or set(cast("dict[str, Any]", record)) != set(_FIELDS):
        raise ConfigError(f"{path}: page {page!r} record is off-schema")
    fields = cast("dict[str, Any]", record)
    blocks = fields["blocks"]
    strings = {key: value for key, value in fields.items() if key != "blocks"}
    if not (
        isinstance(blocks, list)
        and all(isinstance(digest, str) for digest in cast("list[object]", blocks))
        and all(isinstance(value, str) for value in strings.values())
    ):
        raise ConfigError(f"{path}: page {page!r} record is off-schema")
    values = cast("dict[str, str]", strings)
    return PageState(
        source_commit=values["source_commit"],
        source_hash=values["source_hash"],
        blocks=tuple(cast("list[str]", blocks)),
        general_prompt_hash=values["general_prompt_hash"],
        instructions_hash=values["instructions_hash"],
        glossary_hash=values["glossary_hash"],
        model=values["model"],
        translated_at=values["translated_at"],
    )


def save_state(path: Path, state: LanguageState) -> None:
    """Write the state file with stable ordering so its diffs stay reviewable."""
    document = {
        "version": SCHEMA_VERSION,
        "pages": {page: asdict(state.pages[page]) for page in sorted(state.pages)},
    }
    write_text_atomically(path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")


def classify(
    current: dict[str, Fingerprint],
    state: LanguageState,
    translated: set[str],
) -> list[PageStatus]:
    """Classify every English page and every recorded page for one language.

    `current` maps each translatable page to the fingerprint it would have
    if translated now; `translated` is the set of pages with a generated file.
    """
    statuses: list[PageStatus] = []
    for page, fingerprint in current.items():
        record = state.pages.get(page)
        if record is None or page not in translated:
            statuses.append(PageStatus(page, "missing"))
        elif record.fingerprint == fingerprint:
            statuses.append(PageStatus(page, "current"))
        else:
            statuses.append(PageStatus(page, "outdated", _reasons(record.fingerprint, fingerprint)))
    statuses.extend(PageStatus(page, "removable") for page in sorted(set(state.pages) - set(current)))
    return statuses


def _reasons(recorded: Fingerprint, current: Fingerprint) -> tuple[str, ...]:
    """Why a page is outdated, most specific cause first."""
    reasons: list[str] = []
    if recorded.source_hash != current.source_hash:
        reasons.append("English page changed")
    if recorded.general_prompt_hash != current.general_prompt_hash:
        reasons.append("general prompt changed")
    if recorded.instructions_hash != current.instructions_hash:
        reasons.append("language instructions changed")
    if recorded.glossary_hash != current.glossary_hash:
        reasons.append("glossary changed")
    if not reasons and recorded.blocks != current.blocks:
        reasons.append("translation pipeline changed")
    return tuple(reasons)
