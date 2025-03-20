import json
import subprocess
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


def test_command_execution(mock_config_path: Path):
    """Test that the generated command can actually be executed."""
    # Setup
    server_name = "test_server"
    file_spec = "test_server.py:app"

    # Update config
    success = update_claude_config(file_spec=file_spec, server_name=server_name)
    assert success

    # Read the generated config
    config_file = mock_config_path / "claude_desktop_config.json"
    config = json.loads(config_file.read_text())

    # Get the command and args
    server_config = config["mcpServers"][server_name]
    command = server_config["command"]
    args = server_config["args"]

    test_args = [command] + args + ["--help"]

    result = subprocess.run(test_args, capture_output=True, text=True, timeout=5)

    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
