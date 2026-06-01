import subprocess
import sys
from pathlib import Path
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
    """Should return one of the npx candidates on Windows."""
    candidates = ["npx.cmd", "npx.exe", "npx"]
    located = {cmd: f"C:\\Node\\{cmd}" for cmd in candidates}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        assert kw.get("shell") is not True
        assert cmd[0] in located.values()
        if Path(cmd[0]).name in candidates:
            return subprocess.CompletedProcess(cmd, 0)
        else:  # pragma: no cover
            raise subprocess.CalledProcessError(1, cmd[0])

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shutil.which", located.get)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _get_npx_command() in located.values()


def test_get_npx_windows_skips_failed_candidates(monkeypatch: pytest.MonkeyPatch):
    """Should keep checking candidates if one exists but fails."""
    located = {"npx.cmd": "C:\\Node\\npx.cmd", "npx.exe": "C:\\Node\\npx.exe"}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        assert kw.get("shell") is not True
        if cmd[0].endswith("npx.cmd"):
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("shutil.which", located.get)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _get_npx_command() == located["npx.exe"]


def test_get_npx_returns_none_when_npx_missing(monkeypatch: pytest.MonkeyPatch):
    """Should give None if every candidate fails."""
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert _get_npx_command() is None


def test_dev_runs_inspector_without_shell(monkeypatch: pytest.MonkeyPatch):
    """mcp dev should not route file paths or args through a platform shell."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class Server:
        dependencies = ["server-dep"]

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cli_module, "_parse_file_path", lambda file_spec: (Path("server&calc.py"), None))
    monkeypatch.setattr(cli_module, "_import_server", lambda file, server_object: Server())
    monkeypatch.setattr(cli_module, "_build_uv_command", lambda file_spec, with_editable, with_packages: ["uv", "run"])
    monkeypatch.setattr(cli_module, "_get_npx_command", lambda: "C:\\Node\\npx.cmd")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cli_module.dev("server&calc.py", with_packages=["cli-dep"])

    assert exc_info.value.code == 0
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == ["C:\\Node\\npx.cmd", "@modelcontextprotocol/inspector", "uv", "run"]
    assert kwargs["check"] is True
    assert "shell" not in kwargs
