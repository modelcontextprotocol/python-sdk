"""Tests for the atomic file writer the generated files go through (i18n/files.py)."""

from pathlib import Path

import pytest

from i18n.files import write_text_atomically


def test_write_text_atomically_replaces_the_content_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.json"

    write_text_atomically(path, '{"version": 1}\n')
    write_text_atomically(path, '{"version": 1, "pages": {}}\n')

    assert path.read_text(encoding="utf-8") == '{"version": 1, "pages": {}}\n'
    assert list(path.parent.iterdir()) == [path]


def test_a_write_interrupted_before_the_rename_leaves_the_previous_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(source: str, target: Path) -> None:
        raise OSError("simulated crash before the rename")

    monkeypatch.setattr("i18n.files.os.replace", fail_replace)
    with pytest.raises(OSError):
        write_text_atomically(path, '{"new": true}\n')

    # The old bytes survive untouched and the temporary file was cleaned up.
    assert path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert list(tmp_path.iterdir()) == [path]
