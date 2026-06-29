"""Claude app integration utilities."""

import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.utilities.logging import get_logger

logger = get_logger(__name__)


def mcp_requirement(package: str = "mcp") -> str:
    """Requirement string pinning spawned environments to the running SDK version.

    An unpinned `mcp` in a fresh `uv run --with mcp` environment resolves to the latest
    stable release, not the installed one (pre-releases are never selected without a pin).
    Dev/local builds and missing distributions have no published version, so they stay unpinned.
    """
    try:
        version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return package
    if ".dev" in version or "+" in version:
        return package
    return f"{package}=={version}"


def get_claude_config_path() -> Path | None:  # pragma: no cover
    """Get the Claude config directory based on platform."""
    if sys.platform == "win32":
        path = Path(Path.home(), "AppData", "Roaming", "Claude")
    elif sys.platform == "darwin":
        path = Path(Path.home(), "Library", "Application Support", "Claude")
    elif sys.platform.startswith("linux"):
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"), "Claude")
    else:
        return None

    if path.exists():
        return path
    return None


def get_uv_path() -> str:
    """Get the full path to the uv executable."""
    uv_path = shutil.which("uv")
    if not uv_path:
        logger.error(
            "uv executable not found in PATH, falling back to 'uv'. Please ensure uv is installed and in your PATH"
        )
        return "uv"
    return uv_path


def update_claude_config(
    file_spec: str,
    server_name: str,
    *,
    with_editable: Path | None = None,
    with_packages: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
) -> bool:
    """Add or update an MCP server in Claude's configuration.

    Args:
        file_spec: Path to the server file, optionally with `:object` suffix.
        env_vars: Merged with any existing variables, with new values taking precedence.

    Raises:
        RuntimeError: If Claude Desktop's config directory is not found.
    """
    config_dir = get_claude_config_path()
    uv_path = get_uv_path()
    if not config_dir:
        raise RuntimeError(
            "Claude Desktop config directory not found. Please ensure Claude Desktop"
            " is installed and has been run at least once to initialize its config."
        )

    config_file = config_dir / "claude_desktop_config.json"
    if not config_file.exists():  # pragma: lax no cover
        try:
            config_file.write_text("{}")
        except Exception:
            logger.exception(
                "Failed to create Claude config file",
                extra={
                    "config_file": str(config_file),
                },
            )
            return False

    try:
        config = json.loads(config_file.read_text())
        if "mcpServers" not in config:
            config["mcpServers"] = {}

        if server_name in config["mcpServers"] and "env" in config["mcpServers"][server_name]:
            existing_env = config["mcpServers"][server_name]["env"]
            if env_vars:
                env_vars = {**existing_env, **env_vars}
            else:
                env_vars = existing_env

        args = ["run", "--frozen"]

        packages = {mcp_requirement("mcp[cli]")}
        if with_packages:
            packages.update(pkg for pkg in with_packages if pkg)

        for pkg in sorted(packages):
            args.extend(["--with", pkg])

        if with_editable:
            args.extend(["--with-editable", str(with_editable)])

        # Resolve to an absolute path, splitting any :object suffix on the last colon
        # without mistaking a Windows drive letter (C:\...) for one.
        has_windows_drive = len(file_spec) > 1 and file_spec[1] == ":"

        if ":" in (file_spec[2:] if has_windows_drive else file_spec):
            file_path, server_object = file_spec.rsplit(":", 1)
            file_spec = f"{Path(file_path).resolve()}:{server_object}"
        else:
            file_spec = str(Path(file_spec).resolve())

        args.extend(["mcp", "run", file_spec])

        server_config: dict[str, Any] = {"command": uv_path, "args": args}

        if env_vars:
            server_config["env"] = env_vars

        config["mcpServers"][server_name] = server_config

        config_file.write_text(json.dumps(config, indent=2))
        logger.info(
            f"Added server '{server_name}' to Claude config",
            extra={"config_file": str(config_file)},
        )
        return True
    except Exception:  # pragma: no cover
        logger.exception(
            "Failed to update Claude config",
            extra={
                "config_file": str(config_file),
            },
        )
        return False
