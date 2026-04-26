import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from mcp.cli.cli import (  # type: ignore[reportPrivateUsage]
    _build_uv_command,
    _get_npx_command,
    _parse_file_path,
    _resolve_env,
)


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
    assert _get_npx_command() == "npx"


def test_get_npx_windows(monkeypatch: pytest.MonkeyPatch):
    """Should return one of the npx candidates on Windows."""
    candidates = ["npx.cmd", "npx.exe", "npx"]

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        if cmd[0] in candidates:
            return subprocess.CompletedProcess(cmd, 0)
        else:  # pragma: no cover
            raise subprocess.CalledProcessError(1, cmd[0])

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _get_npx_command() in candidates


def test_get_npx_returns_none_when_npx_missing(monkeypatch: pytest.MonkeyPatch):
    """Should give None if every candidate fails."""
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    def always_fail(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(subprocess, "run", always_fail)
    assert _get_npx_command() is None


def test_resolve_env_returns_none_when_nothing_provided():
    """No env file and no env vars should yield None."""
    assert _resolve_env(None, []) is None


def test_resolve_env_parses_inline_vars():
    """Repeated KEY=VALUE flags should be parsed into a dict."""
    assert _resolve_env(None, ["FOO=bar", "BAZ=qux"]) == {"FOO": "bar", "BAZ": "qux"}


def test_resolve_env_handles_value_with_equals():
    """Values containing '=' should be preserved (only the first '=' splits)."""
    assert _resolve_env(None, ["DB_URL=postgres://u:p@host/db?x=1"]) == {"DB_URL": "postgres://u:p@host/db?x=1"}


def test_resolve_env_loads_dotenv_file(tmp_path: Path):
    """Values from a .env file should be loaded."""
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from_file\nBAR=also_from_file\n")
    assert _resolve_env(env_file, []) == {"FOO": "from_file", "BAR": "also_from_file"}


def test_resolve_env_inline_vars_override_dotenv(tmp_path: Path):
    """Inline -v flags should override values from --env-file."""
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from_file\nBAR=keep_me\n")
    result = _resolve_env(env_file, ["FOO=from_cli"])
    assert result == {"FOO": "from_cli", "BAR": "keep_me"}
