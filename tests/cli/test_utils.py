import subprocess
import sys
from pathlib import Path

import pytest

from mcp.cli.cli import _build_uv_command, _get_npx_command, _parse_file_path


@pytest.mark.parametrize(
    "spec, expected_obj",
    [
        ("server.py", None),
        ("foo.py:srv_obj", "srv_obj"),
    ],
)
def test_parse_file_path_accepts_valid_specs(tmp_path, spec, expected_obj):
    """Should accept valid file specs."""
    file = tmp_path / spec.split(":")[0]
    file.write_text("x = 1")
    path, obj = _parse_file_path(f"{file}:{expected_obj}" if ":" in spec else str(file))
    assert path == file.resolve()
    assert obj == expected_obj


def test_parse_file_path_missing(tmp_path):
    """Should system exit if a file is missing."""
    with pytest.raises(SystemExit):
        _parse_file_path(str(tmp_path / "missing.py"))


def test_parse_file_exit_on_dir(tmp_path):
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


def test_get_npx_unix_like(monkeypatch):
    """Should return "npx" on unix-like systems."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert _get_npx_command() == "npx"


def test_get_npx_windows(monkeypatch):
    """Should return one of the npx candidates on Windows."""
    candidates = ["npx.cmd", "npx.exe", "npx"]

    def fake_run(cmd, **kw):
        if cmd[0] in candidates:
            return subprocess.CompletedProcess(cmd, 0)
        else:
            raise subprocess.CalledProcessError(1, cmd[0])

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _get_npx_command() in candidates


def test_get_npx_returns_none_when_npx_missing(monkeypatch):
    """Should give None if every candidate fails."""
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    def always_fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(subprocess, "run", always_fail)
    assert _get_npx_command() is None
