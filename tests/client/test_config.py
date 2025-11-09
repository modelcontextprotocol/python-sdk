import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp.cli.claude import update_claude_config


@pytest.fixture
def temp_config_dir(tmp_path: Path):
    """Create a temporary Claude config directory."""
    config_dir = tmp_path / "Claude"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def mock_config_path(temp_config_dir: Path):
    """Mock get_claude_config_path to return our temporary directory."""
    with patch("mcp.cli.claude.get_claude_config_path", return_value=temp_config_dir):
        yield temp_config_dir


def test_basic_config_creation(mock_config_path: Path):
    """Test that config file is created with correct structure."""
    success = update_claude_config(file_spec="server.py:app", server_name="test")

    assert success
    config_file = mock_config_path / "claude_desktop_config.json"
    assert config_file.exists()

    config = json.loads(config_file.read_text())
    assert "mcpServers" in config
    assert "test" in config["mcpServers"]

    server = config["mcpServers"]["test"]
    assert "command" in server
    assert "args" in server
    # Command should be the path to uv executable
    assert server["command"].lower().endswith("uv") or server["command"].lower().endswith("uv.exe")


def test_args_structure(mock_config_path: Path):
    """Test that args are built correctly."""
    success = update_claude_config(file_spec="server.py:app", server_name="test")
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    # Should be: ["run", "--with", "mcp[cli]", "mcp", "run", "/abs/path/server.py:app"]
    assert args[0] == "run"
    assert "--with" in args
    assert "mcp[cli]" in args
    assert "mcp" in args
    assert args[args.index("mcp") + 1] == "run"
    assert args[-1].endswith("server.py:app")


def test_absolute_file_path_resolution(mock_config_path: Path, tmp_path: Path):
    """Test that file paths are resolved to absolute paths."""
    # Create a test file
    server_file = tmp_path / "my_server.py"
    server_file.write_text("# test")

    success = update_claude_config(file_spec=str(server_file) + ":app", server_name="test")
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    # Last arg should be absolute path with :app suffix
    assert args[-1] == f"{server_file.resolve()}:app"
    # Split on last colon to extract path (handles Windows drive letters like C:)
    file_path = args[-1].rsplit(":", 1)[0]
    assert Path(file_path).is_absolute()


def test_env_vars_initial(mock_config_path: Path):
    """Test that environment variables are set correctly on initial config."""
    success = update_claude_config(
        file_spec="server.py:app", server_name="test", env_vars={"KEY1": "value1", "KEY2": "value2"}
    )
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    env = config["mcpServers"]["test"]["env"]

    assert env["KEY1"] == "value1"
    assert env["KEY2"] == "value2"


def test_env_vars_merged(mock_config_path: Path):
    """Test that environment variables are merged correctly on update."""
    # First call with env vars
    update_claude_config(file_spec="server.py:app", server_name="test", env_vars={"KEY1": "value1", "KEY2": "value2"})

    # Second call with overlapping env vars
    update_claude_config(
        file_spec="server.py:app", server_name="test", env_vars={"KEY2": "new_value", "KEY3": "value3"}
    )

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    env = config["mcpServers"]["test"]["env"]

    assert env["KEY1"] == "value1"  # Preserved
    assert env["KEY2"] == "new_value"  # Updated
    assert env["KEY3"] == "value3"  # Added


def test_env_vars_preserved_when_none(mock_config_path: Path):
    """Test that existing env vars are preserved when update doesn't specify any."""
    # First call with env vars
    update_claude_config(file_spec="server.py:app", server_name="test", env_vars={"KEY1": "value1"})

    # Second call without env vars
    update_claude_config(file_spec="server.py:app", server_name="test")

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    env = config["mcpServers"]["test"]["env"]

    assert env["KEY1"] == "value1"  # Should still be there


def test_multiple_packages(mock_config_path: Path):
    """Test that multiple packages are included with --with."""
    success = update_claude_config(file_spec="server.py:app", server_name="test", with_packages=["requests", "httpx"])
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    # Should have: --with mcp[cli] --with httpx --with requests (sorted)
    with_indices = [i for i, arg in enumerate(args) if arg == "--with"]
    assert len(with_indices) == 3

    packages = [args[i + 1] for i in with_indices]
    assert "mcp[cli]" in packages
    assert "httpx" in packages
    assert "requests" in packages


def test_package_deduplication(mock_config_path: Path):
    """Test that duplicate packages are deduplicated."""
    success = update_claude_config(
        file_spec="server.py:app", server_name="test", with_packages=["mcp[cli]", "requests", "requests"]
    )
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    # Count --with flags
    with_count = sum(1 for arg in args if arg == "--with")
    # Should have mcp[cli] and requests only once each
    assert with_count == 2


def test_editable_package(mock_config_path: Path, tmp_path: Path):
    """Test that editable package is added correctly."""
    editable_dir = tmp_path / "my_package"
    editable_dir.mkdir()

    success = update_claude_config(file_spec="server.py:app", server_name="test", with_editable=editable_dir)
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    assert "--with-editable" in args
    idx = args.index("--with-editable")
    assert args[idx + 1] == str(editable_dir)


def test_preserves_other_servers(mock_config_path: Path):
    """Test that existing servers are preserved when adding a new one."""
    # Create config with existing server
    config_file = mock_config_path / "claude_desktop_config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"existing_server": {"command": "some_command", "args": ["arg1", "arg2"]}}})
    )

    # Add new server
    success = update_claude_config(file_spec="server.py:app", server_name="new_server")
    assert success

    config = json.loads(config_file.read_text())
    assert "existing_server" in config["mcpServers"]
    assert "new_server" in config["mcpServers"]
    assert config["mcpServers"]["existing_server"]["command"] == "some_command"
    assert config["mcpServers"]["existing_server"]["args"] == ["arg1", "arg2"]


def test_updates_existing_server(mock_config_path: Path):
    """Test that updating an existing server replaces command/args but merges env vars."""
    # Create initial server
    update_claude_config(file_spec="old_server.py:app", server_name="test", env_vars={"OLD": "value"})

    # Update the same server
    update_claude_config(file_spec="new_server.py:app", server_name="test", env_vars={"NEW": "value"})

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    # Should have new file spec
    assert args[-1].endswith("new_server.py:app")
    # Env vars should be merged (NEW takes precedence but OLD is preserved)
    assert "NEW" in config["mcpServers"]["test"]["env"]
    assert "OLD" in config["mcpServers"]["test"]["env"]


def test_error_handling_missing_config_dir(tmp_path: Path):
    """Test that missing config directory raises appropriate error."""
    with patch("mcp.cli.claude.get_claude_config_path", return_value=None):
        with pytest.raises(RuntimeError, match="Claude Desktop config directory not found"):
            update_claude_config(file_spec="server.py:app", server_name="test")


def test_file_spec_without_colon(mock_config_path: Path, tmp_path: Path):
    """Test file spec without :object suffix."""
    server_file = tmp_path / "server.py"
    server_file.write_text("# test")

    success = update_claude_config(file_spec=str(server_file), server_name="test")
    assert success

    config = json.loads((mock_config_path / "claude_desktop_config.json").read_text())
    args = config["mcpServers"]["test"]["args"]

    # Last arg should be absolute path without object suffix
    assert args[-1] == str(server_file.resolve())
    # Verify no object suffix was added (like :app) - check it doesn't end with :identifier
    assert not re.search(r":\w+$", args[-1]), "Should not have object suffix like :app"


def test_absolute_uv_path(mock_config_path: Path):
    """Test that the absolute path to uv is used when available."""
    # Mock the get_uv_path function to return a fake path
    mock_uv_path = "/usr/local/bin/uv"

    with patch("mcp.cli.claude.get_uv_path", return_value=mock_uv_path):
        # Setup
        server_name = "test_server"
        file_spec = "test_server.py:app"

        # Update config
        success = update_claude_config(file_spec=file_spec, server_name=server_name)
        assert success

        # Read the generated config
        config_file = mock_config_path / "claude_desktop_config.json"
        config = json.loads(config_file.read_text())

        # Verify the command is the absolute path
        server_config = config["mcpServers"][server_name]
        command = server_config["command"]

        assert command == mock_uv_path


def test_creates_mcpservers_key_if_missing(mock_config_path: Path):
    """Test that mcpServers key is created if config exists but key is missing."""
    config_file = mock_config_path / "claude_desktop_config.json"
    config_file.write_text(json.dumps({"someOtherKey": "value"}))

    success = update_claude_config(file_spec="server.py:app", server_name="test")
    assert success

    config = json.loads(config_file.read_text())
    assert "mcpServers" in config
    assert "someOtherKey" in config  # Original content preserved
    assert config["someOtherKey"] == "value"
