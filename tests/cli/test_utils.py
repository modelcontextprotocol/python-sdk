import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp.cli import cli as cli_module
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
    assert _get_npx_command() == "npx"


def test_get_npx_windows(monkeypatch: pytest.MonkeyPatch):
    """Should return the first Windows npx executable found on PATH."""
    resolved_commands = {
        "npx.cmd": r"C:\Program Files\nodejs\npx.cmd",
        "npx.exe": None,
        "npx": None,
    }

    def fake_which(cmd: str) -> str | None:
        return resolved_commands.get(cmd)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shutil.which", fake_which)
    assert _get_npx_command() == r"C:\Program Files\nodejs\npx.cmd"


def test_get_npx_returns_none_when_npx_missing(monkeypatch: pytest.MonkeyPatch):
    """Should give None if every candidate fails."""
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert _get_npx_command() is None


def test_dev_runs_inspector_without_shell_on_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Should invoke the inspector with a resolved executable and shell=False on Windows."""
    server_file = tmp_path / "server.py"
    server_file.write_text("x = 1")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli_module, "_parse_file_path", lambda file_spec: (server_file, None))
    monkeypatch.setattr(cli_module, "_import_server", lambda file, server_object: SimpleNamespace(dependencies=[]))
    monkeypatch.setattr(
        cli_module,
        "_build_uv_command",
        lambda file_spec, with_editable=None, with_packages=None: [
            "uv",
            "run",
            "--with",
            "mcp",
            "mcp",
            "run",
            file_spec,
        ],
    )
    monkeypatch.setattr(cli_module, "_get_npx_command", lambda: r"C:\Program Files\nodejs\npx.cmd")

    recorded: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        recorded["cmd"] = cmd
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        cli_module.dev(str(server_file))

    assert excinfo.value.code == 0
    assert recorded["cmd"] == [
        r"C:\Program Files\nodejs\npx.cmd",
        "@modelcontextprotocol/inspector",
        "uv",
        "run",
        "--with",
        "mcp",
        "mcp",
        "run",
        str(server_file),
    ]
    assert recorded["kwargs"]["check"] is True
    assert recorded["kwargs"]["env"] == dict(os.environ.items())
    assert recorded["kwargs"].get("shell", False) is False
