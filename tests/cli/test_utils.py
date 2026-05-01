import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from mcp.cli import cli
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

    def fake_which(cmd: str) -> str | None:
        return f"C:\\node\\{cmd}" if cmd in candidates else None

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    assert _get_npx_command() == "C:\\node\\npx.cmd"


def test_get_npx_returns_none_when_npx_missing(monkeypatch: pytest.MonkeyPatch):
    """Should give None if every candidate fails."""
    monkeypatch.setattr(sys, "platform", "win32", raising=False)

    def no_npx(_cmd: str) -> str | None:
        return None

    monkeypatch.setattr(cli.shutil, "which", no_npx)
    assert _get_npx_command() is None


def test_dev_uses_arg_list_without_shell_on_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Should not route user-controlled dev paths through cmd.exe on Windows."""
    server_path = tmp_path / "server&calc.py"
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0)

    def fake_parse_file_path(_file_spec: str) -> tuple[Path, str | None]:
        return server_path, None

    def fake_import_server(_file: Path, _server_object: str | None) -> object:
        return object()

    def fake_get_npx_command() -> str:
        return "C:\\node\\npx.cmd"

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_parse_file_path", fake_parse_file_path)
    monkeypatch.setattr(cli, "_import_server", fake_import_server)
    monkeypatch.setattr(cli, "_get_npx_command", fake_get_npx_command)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.dev(str(server_path))

    assert exc_info.value.code == 0
    assert captured["cmd"][-1] == str(server_path)
    assert captured["kwargs"].get("shell") is not True


def test_dev_adds_server_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Should include dependencies declared by the imported server."""
    server_path = tmp_path / "server.py"
    captured: dict[str, Any] = {}

    class Server:
        dependencies = ["server-extra"]

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0)

    def fake_parse_file_path(_file_spec: str) -> tuple[Path, str | None]:
        return server_path, None

    def fake_import_server(_file: Path, _server_object: str | None) -> object:
        return Server()

    monkeypatch.setattr(cli, "_parse_file_path", fake_parse_file_path)
    monkeypatch.setattr(cli, "_import_server", fake_import_server)
    monkeypatch.setattr(cli, "_get_npx_command", lambda: "npx")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.dev(str(server_path), with_packages=["direct-extra"])

    assert exc_info.value.code == 0
    with_values = [captured["cmd"][index + 1] for index, value in enumerate(captured["cmd"]) if value == "--with"]
    assert with_values[0] == "mcp"
    assert set(with_values[1:]) == {"direct-extra", "server-extra"}


def test_dev_exits_when_npx_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Should exit before spawning the inspector if npx cannot be found."""
    server_path = tmp_path / "server.py"

    def fake_parse_file_path(_file_spec: str) -> tuple[Path, str | None]:
        return server_path, None

    def fake_import_server(_file: Path, _server_object: str | None) -> object:
        return object()

    monkeypatch.setattr(cli, "_parse_file_path", fake_parse_file_path)
    monkeypatch.setattr(cli, "_import_server", fake_import_server)
    monkeypatch.setattr(cli, "_get_npx_command", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        cli.dev(str(server_path))

    assert exc_info.value.code == 1


def test_dev_exits_with_process_returncode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Should propagate inspector process failures."""
    server_path = tmp_path / "server.py"

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(7, cmd)

    def fake_parse_file_path(_file_spec: str) -> tuple[Path, str | None]:
        return server_path, None

    def fake_import_server(_file: Path, _server_object: str | None) -> object:
        return object()

    monkeypatch.setattr(cli, "_parse_file_path", fake_parse_file_path)
    monkeypatch.setattr(cli, "_import_server", fake_import_server)
    monkeypatch.setattr(cli, "_get_npx_command", lambda: "npx")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.dev(str(server_path))

    assert exc_info.value.code == 7


def test_dev_exits_when_subprocess_cannot_find_npx(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Should handle npx disappearing after discovery."""
    server_path = tmp_path / "server.py"

    def fake_run(_cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError()

    def fake_parse_file_path(_file_spec: str) -> tuple[Path, str | None]:
        return server_path, None

    def fake_import_server(_file: Path, _server_object: str | None) -> object:
        return object()

    monkeypatch.setattr(cli, "_parse_file_path", fake_parse_file_path)
    monkeypatch.setattr(cli, "_import_server", fake_import_server)
    monkeypatch.setattr(cli, "_get_npx_command", lambda: "npx")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.dev(str(server_path))

    assert exc_info.value.code == 1
