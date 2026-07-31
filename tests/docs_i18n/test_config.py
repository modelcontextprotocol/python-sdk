"""Tests for the language registry loader (i18n/config.py)."""

from pathlib import Path

import pytest

from i18n.config import ConfigError, Language, load_registry
from tests.docs_i18n._repo import make_repo


def test_load_registry_reads_each_language_with_its_script(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    registry = load_registry(repo.i18n / "languages.yml")

    assert registry.languages == (Language("xx", "Testish", "en", "xx", "latin", True),)
    assert registry.exclude_pages == ("migration.md", "api/**")
    assert (registry.models.translate, registry.models.verify) == ("model-t", "model-v")


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (("    script: latin\n", ""), "languages.yml: a languages entry is missing keys ['script']"),
        (
            ("    script: latin\n", "    script: latn\n"),
            "languages.yml: languages[xx].script must be one of ['latin', 'cjk', 'hangul'], found 'latn'",
        ),
    ],
)
def test_load_registry_requires_a_known_script(tmp_path: Path, edit: tuple[str, str], message: str) -> None:
    repo = make_repo(tmp_path)
    registry_path = repo.i18n / "languages.yml"
    registry_path.write_text(registry_path.read_text(encoding="utf-8").replace(*edit), encoding="utf-8")

    with pytest.raises(ConfigError) as failure:
        load_registry(registry_path)

    assert str(failure.value) == message
