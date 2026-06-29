import importlib.metadata
import json
from pathlib import Path
from typing import Any

import pytest

from mcp.cli.claude import get_uv_path, mcp_requirement, update_claude_config


def _set_mcp_version(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    real_version = importlib.metadata.version

    def fake_version(distribution_name: str) -> str:
        return version if distribution_name == "mcp" else real_version(distribution_name)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claude_dir = tmp_path / "Claude"
    claude_dir.mkdir()
    monkeypatch.setattr("mcp.cli.claude.get_claude_config_path", lambda: claude_dir)
    monkeypatch.setattr("mcp.cli.claude.get_uv_path", lambda: "/fake/bin/uv")
    # Pin the SDK version (a dev build in the repo venv) so the generated --with requirement is stable.
    _set_mcp_version(monkeypatch, "1.2.3")
    return claude_dir


def test_mcp_requirement_pins_release_versions(monkeypatch: pytest.MonkeyPatch):
    _set_mcp_version(monkeypatch, "2.0.0a1")
    assert mcp_requirement() == "mcp==2.0.0a1"
    assert mcp_requirement("mcp[cli]") == "mcp[cli]==2.0.0a1"


def test_mcp_requirement_leaves_dev_versions_unpinned(monkeypatch: pytest.MonkeyPatch):
    """Dev versions are not on PyPI, so no pin is emitted."""
    _set_mcp_version(monkeypatch, "2.0.0a2.dev3")
    assert mcp_requirement() == "mcp"
    assert mcp_requirement("mcp[cli]") == "mcp[cli]"


def test_mcp_requirement_leaves_local_versions_unpinned(monkeypatch: pytest.MonkeyPatch):
    """Local version segments (source builds) are not on PyPI, so no pin is emitted."""
    _set_mcp_version(monkeypatch, "1.2.3+g0123abc")
    assert mcp_requirement() == "mcp"


def test_mcp_requirement_falls_back_when_mcp_is_not_installed(monkeypatch: pytest.MonkeyPatch):
    def raise_not_found(distribution_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(distribution_name)

    monkeypatch.setattr(importlib.metadata, "version", raise_not_found)
    assert mcp_requirement() == "mcp"
    assert mcp_requirement("mcp[cli]") == "mcp[cli]"


def _read_server(config_dir: Path, name: str) -> dict[str, Any]:
    config = json.loads((config_dir / "claude_desktop_config.json").read_text())
    return config["mcpServers"][name]


def test_generates_uv_run_command(config_dir: Path):
    assert update_claude_config(file_spec="server.py:app", server_name="my_server")

    resolved = Path("server.py").resolve()
    assert _read_server(config_dir, "my_server") == {
        "command": "/fake/bin/uv",
        "args": ["run", "--frozen", "--with", "mcp[cli]==1.2.3", "mcp", "run", f"{resolved}:app"],
    }


def test_file_spec_without_object_suffix(config_dir: Path):
    assert update_claude_config(file_spec="server.py", server_name="s")

    assert _read_server(config_dir, "s")["args"][-1] == str(Path("server.py").resolve())


def test_with_packages_sorted_and_deduplicated(config_dir: Path):
    assert update_claude_config(file_spec="s.py:app", server_name="s", with_packages=["zebra", "aardvark", "zebra"])

    args = _read_server(config_dir, "s")["args"]
    assert args[:8] == ["run", "--frozen", "--with", "aardvark", "--with", "mcp[cli]==1.2.3", "--with", "zebra"]


def test_explicit_mcp_cli_kept_alongside_pinned_requirement(config_dir: Path):
    """Both requirements are emitted; uv resolves them to the pinned version."""
    assert update_claude_config(file_spec="s.py:app", server_name="s", with_packages=["mcp[cli]"])

    args = _read_server(config_dir, "s")["args"]
    assert args[:6] == ["run", "--frozen", "--with", "mcp[cli]", "--with", "mcp[cli]==1.2.3"]


def test_with_editable_adds_flag(config_dir: Path, tmp_path: Path):
    editable = tmp_path / "project"
    assert update_claude_config(file_spec="s.py:app", server_name="s", with_editable=editable)

    args = _read_server(config_dir, "s")["args"]
    assert args[4:6] == ["--with-editable", str(editable)]


def test_env_vars_written(config_dir: Path):
    assert update_claude_config(file_spec="s.py:app", server_name="s", env_vars={"KEY": "val"})

    assert _read_server(config_dir, "s")["env"] == {"KEY": "val"}


def test_existing_env_vars_merged_new_wins(config_dir: Path):
    (config_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"s": {"env": {"OLD": "keep", "KEY": "old"}}}})
    )

    assert update_claude_config(file_spec="s.py:app", server_name="s", env_vars={"KEY": "new"})

    assert _read_server(config_dir, "s")["env"] == {"OLD": "keep", "KEY": "new"}


def test_existing_env_vars_preserved_without_new(config_dir: Path):
    (config_dir / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {"s": {"env": {"KEEP": "me"}}}}))

    assert update_claude_config(file_spec="s.py:app", server_name="s")

    assert _read_server(config_dir, "s")["env"] == {"KEEP": "me"}


def test_other_servers_preserved(config_dir: Path):
    (config_dir / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    assert update_claude_config(file_spec="s.py:app", server_name="s")

    config = json.loads((config_dir / "claude_desktop_config.json").read_text())
    assert set(config["mcpServers"]) == {"other", "s"}
    assert config["mcpServers"]["other"] == {"command": "x"}


def test_raises_when_config_dir_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("mcp.cli.claude.get_claude_config_path", lambda: None)
    monkeypatch.setattr("mcp.cli.claude.get_uv_path", lambda: "/fake/bin/uv")

    with pytest.raises(RuntimeError, match="Claude Desktop config directory not found"):
        update_claude_config(file_spec="s.py:app", server_name="s")


@pytest.mark.parametrize("which_result, expected", [("/usr/local/bin/uv", "/usr/local/bin/uv"), (None, "uv")])
def test_get_uv_path(monkeypatch: pytest.MonkeyPatch, which_result: str | None, expected: str):
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
    """Regression: 'C:\\Users\\server.py' once hit rsplit(":", 1), resolving Path("C") instead of the full path."""
    seen: list[str] = []

    def fake_resolve(self: Path) -> Path:
        seen.append(str(self))
        return self

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    assert update_claude_config(file_spec=file_spec, server_name="s")

    assert seen == ["C:\\Users\\server.py"]
    assert _read_server(config_dir, "s")["args"][-1] == expected_last_arg
