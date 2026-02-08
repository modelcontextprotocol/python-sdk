import sys
from pathlib import Path

import pytest

from mcp.cli.cli import _build_uv_command, _get_npx_command, _parse_file_path  # type: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "spec, expected_obj",
    [
        ("server.py", None),
        ("foo.py:srv_obj", "srv_obj"),
    ],
)
def test_parse_file_path_accepts_valid_specs(tmp_path: Path, spec: str, expected_obj: str | None):
    """Should accept valid file specs."""
    file = tmp_path / spec.split(":")[0]
    file.write_text("x = 1")
    path, obj = _parse_file_path(f"{file}:{expected_obj}" if ":" in spec else str(file))
    assert path == file.resolve()
    assert obj == expected_obj


def test_parse_file_path_missing(tmp_path: Path):
    """Should system exit if a file is missing."""
    with pytest.raises(SystemExit):
        _parse_file_path(str(tmp_path / "missing.py"))


def test_parse_file_exit_on_dir(tmp_path: Path):
    """Should system exit if a directory is passed"""
    dir_path = tmp_path / "dir"
    dir_path.mkdir()
    with pytest.raises(SystemExit):
        _parse_file_path(str(dir_path))


def test_build_uv_command_minimal():
    """Should emit core command when no extras specified."""
    cmd = _build_uv_command("foo.py")
    assert cmd == ["uv", "run", "--with", "mcp", "mcp", "run", "foo.py"]


def test_build_uv_command_adds_editable_and_packages():
    """Should include --with-editable and every --with pkg in correct order."""
    test_path = Path("/pkg")
    cmd = _build_uv_command(
        "foo.py",
        with_editable=test_path,
        with_packages=["package1", "package2"],
    )
    assert cmd == [
        "uv",
        "run",
        "--with",
        "mcp",
        "--with-editable",
        str(test_path),  # Use str() to match what the function does
        "--with",
        "package1",
        "--with",
        "package2",
        "mcp",
        "run",
        "foo.py",
    ]


def test_get_npx_unix_like(monkeypatch: pytest.MonkeyPatch):
    """Should return "npx" on unix-like systems."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert _get_npx_command() == ["npx"]


def test_get_npx_windows(monkeypatch: pytest.MonkeyPatch):
    """Should return a subprocess-friendly command prefix on Windows."""
    import shutil

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\bin\\npx.exe" if name == "npx.exe" else None)
    assert _get_npx_command() == ["C:\\bin\\npx.exe"]


def test_get_npx_windows_cmd_wrapper(monkeypatch: pytest.MonkeyPatch):
    """Should wrap .cmd/.bat shims via COMSPEC on Windows."""
    import shutil

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", "cmd.exe")
    monkeypatch.setattr(shutil, "which", lambda name: "C:\\bin\\npx.cmd" if name == "npx.cmd" else None)

    assert _get_npx_command() == ["cmd.exe", "/c", "C:\\bin\\npx.cmd"]


def test_get_npx_returns_none_when_npx_missing(monkeypatch: pytest.MonkeyPatch):
    """Should give None if every candidate fails."""
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _get_npx_command() is None
