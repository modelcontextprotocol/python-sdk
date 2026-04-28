"""Tests for mcp.cli.claude — Claude Desktop config file generation."""

import json
from pathlib import Path
from typing import Any

import pytest

from mcp.cli.claude import get_uv_path, update_claude_config


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp Claude config dir with get_claude_config_path and get_uv_path mocked."""
    claude_dir = tmp_path / "Claude"
    claude_dir.mkdir()
    monkeypatch.setattr("mcp.cli.claude.get_claude_config_path", lambda: claude_dir)
    monkeypatch.setattr("mcp.cli.claude.get_uv_path", lambda: "/fake/bin/uv")
    return claude_dir


def _read_server(config_dir: Path, name: str) -> dict[str, Any]:
    config = json.loads((config_dir / "claude_desktop_config.json").read_text())
    return config["mcpServers"][name]


def test_generates_uv_run_command(config_dir: Path):
    """Should write a uv run command that invokes mcp run on the resolved file spec."""
    assert update_claude_config(file_spec="server.py:app", server_name="my_server")

    resolved = Path("server.py").resolve()
    assert _read_server(config_dir, "my_server") == {
        "command": "/fake/bin/uv",
        "args": ["run", "--frozen", "--with", "mcp[cli]", "mcp", "run", f"{resolved}:app"],
    }


def test_file_spec_without_object_suffix(config_dir: Path):
    """File specs without :object should still resolve to an absolute path."""
    assert update_claude_config(file_spec="server.py", server_name="s")

    assert _read_server(config_dir, "s")["args"][-1] == str(Path("server.py").resolve())


def test_with_packages_sorted_and_deduplicated(config_dir: Path):
    """Extra packages should appear as --with flags, sorted and deduplicated with mcp[cli]."""
    assert update_claude_config(file_spec="s.py:app", server_name="s", with_packages=["zebra", "aardvark", "zebra"])

    args = _read_server(config_dir, "s")["args"]
    assert args[:8] == ["run", "--frozen", "--with", "aardvark", "--with", "mcp[cli]", "--with", "zebra"]


def test_with_editable_adds_flag(config_dir: Path, tmp_path: Path):
    """with_editable should add --with-editable after the --with flags."""
    editable = tmp_path / "project"
    assert update_claude_config(file_spec="s.py:app", server_name="s", with_editable=editable)

    args = _read_server(config_dir, "s")["args"]
    assert args[4:6] == ["--with-editable", str(editable)]


def test_env_vars_written(config_dir: Path):
    """env_vars should be written under the server's env key."""
    assert update_claude_config(file_spec="s.py:app", server_name="s", env_vars={"KEY": "val"})

    assert _read_server(config_dir, "s")["env"] == {"KEY": "val"}


def test_existing_env_vars_merged_new_wins(config_dir: Path):
    """Re-installing should merge env vars, with new values overriding existing ones."""
    (config_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"s": {"env": {"OLD": "keep", "KEY": "old"}}}})
    )

    assert update_claude_config(file_spec="s.py:app", server_name="s", env_vars={"KEY": "new"})

    assert _read_server(config_dir, "s")["env"] == {"OLD": "keep", "KEY": "new"}


def test_existing_env_vars_preserved_without_new(config_dir: Path):
    """Re-installing without env_vars should keep the existing env block intact."""
    (config_dir / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {"s": {"env": {"KEEP": "me"}}}}))

    assert update_claude_config(file_spec="s.py:app", server_name="s")

    assert _read_server(config_dir, "s")["env"] == {"KEEP": "me"}


def test_other_servers_preserved(config_dir: Path):
    """Installing a new server should not clobber existing mcpServers entries."""
    (config_dir / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    assert update_claude_config(file_spec="s.py:app", server_name="s")

    config = json.loads((config_dir / "claude_desktop_config.json").read_text())
    assert set(config["mcpServers"]) == {"other", "s"}
    assert config["mcpServers"]["other"] == {"command": "x"}


def test_raises_when_config_dir_missing(monkeypatch: pytest.MonkeyPatch):
    """Should raise RuntimeError when Claude Desktop config dir can't be found."""
    monkeypatch.setattr("mcp.cli.claude.get_claude_config_path", lambda: None)
    monkeypatch.setattr("mcp.cli.claude.get_uv_path", lambda: "/fake/bin/uv")

    with pytest.raises(RuntimeError, match="Claude Desktop config directory not found"):
        update_claude_config(file_spec="s.py:app", server_name="s")


@pytest.mark.parametrize("which_result, expected", [("/usr/local/bin/uv", "/usr/local/bin/uv"), (None, "uv")])
def test_get_uv_path(monkeypatch: pytest.MonkeyPatch, which_result: str | None, expected: str):
    """Should return shutil.which's result, or fall back to bare 'uv' when not on PATH."""

    def fake_which(cmd: str) -> str | None:
        return which_result

    monkeypatch.setattr("shutil.which", fake_which)
    assert get_uv_path() == expected


@pytest.mark.parametrize(
    "file_spec, expected_last_arg",
    [
        ("C:\\Users\\server.py", "C:\\Users\\server.py"),
        ("C:\\Users\\server.py:app", "C:\\Users\\server.py:app"),
    ],
)
def test_windows_drive_letter_not_split(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch, file_spec: str, expected_last_arg: str
):
    """Drive-letter paths like 'C:\\server.py' must not be split on the drive colon.

    Before the fix, a bare 'C:\\path\\server.py' would hit rsplit(":", 1) and yield
    ("C", "\\path\\server.py"), calling resolve() on Path("C") instead of the full path.
    """
    seen: list[str] = []

    def fake_resolve(self: Path) -> Path:
        seen.append(str(self))
        return self

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    assert update_claude_config(file_spec=file_spec, server_name="s")

    assert seen == ["C:\\Users\\server.py"]
    assert _read_server(config_dir, "s")["args"][-1] == expected_last_arg
