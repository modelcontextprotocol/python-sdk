"""The prompt inputs of one language and the fingerprints they contribute.

A language's translations are a pure function of four texts — the English
page, the general prompt, the language's instructions and its glossary — and
the pipeline version. Hashing all of them into every block hash is what makes
`status` notice an instructions or glossary edit as an outdated translation
without any bookkeeping beyond the state file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from i18n.config import ConfigError, Language, general_prompt_path, glossary_path, instructions_path
from i18n.glossary import Glossary, load_glossary
from i18n.nav import NavFingerprint, labels_hash
from i18n.pages import block_hashes, block_salt, sha256, split_blocks
from i18n.state import Fingerprint


@dataclass(frozen=True)
class LanguageInputs:
    """Everything a language's prompts are assembled from, plus its fingerprints."""

    language: Language
    general_prompt: str
    instructions: str
    glossary: Glossary
    general_prompt_hash: str
    instructions_hash: str
    glossary_hash: str

    @property
    def salt(self) -> str:
        """The salt every block hash for this language mixes in."""
        return block_salt(self.general_prompt_hash, self.instructions_hash, self.glossary_hash)

    def fingerprint(self, english: str) -> Fingerprint:
        """What a translation of `english` made right now would record."""
        return Fingerprint(
            source_hash=sha256(english),
            blocks=tuple(block_hashes(split_blocks(english), self.salt)),
            general_prompt_hash=self.general_prompt_hash,
            instructions_hash=self.instructions_hash,
            glossary_hash=self.glossary_hash,
        )

    def nav_fingerprint(self, labels: Sequence[str]) -> NavFingerprint:
        """What a translation of the nav `labels` made right now would record."""
        return NavFingerprint(
            labels_hash=labels_hash(labels),
            general_prompt_hash=self.general_prompt_hash,
            instructions_hash=self.instructions_hash,
            glossary_hash=self.glossary_hash,
        )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def load_inputs(language: Language, i18n_dir: Path) -> LanguageInputs:
    """Read and fingerprint one language's prompt inputs.

    Raises:
        ConfigError: A required input file is missing or invalid.
    """
    general = _read(general_prompt_path(i18n_dir))
    instructions = _read(instructions_path(language.code, i18n_dir))
    glossary_file = glossary_path(language.code, i18n_dir)
    glossary = load_glossary(glossary_file)
    return LanguageInputs(
        language=language,
        general_prompt=general,
        instructions=instructions,
        glossary=glossary,
        general_prompt_hash=sha256(general),
        instructions_hash=sha256(instructions),
        glossary_hash=sha256(_read(glossary_file)),
    )
