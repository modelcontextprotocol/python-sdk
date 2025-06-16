"""Configuration management for MCP servers."""

# stdlib imports
import json
from pathlib import Path
from typing import Annotated, Any, Literal

# third party imports
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore
from pydantic import BaseModel, Field, field_validator


class MCPServerConfig(BaseModel):
    """Base class for MCP server configurations."""

    pass


class StdioServerConfig(MCPServerConfig):
    """Configuration for stdio-based MCP servers."""

    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] | None = None
    env: dict[str, str] | None = None

    @property
    def effective_command(self) -> str:
        """Get the effective command (first part of the command string)."""
        return self.command.split()[0]

    @property
    def effective_args(self) -> list[str]:
        """Get the effective arguments (parsed from command plus explicit args)."""
        command_parts = self.command.split()
        parsed_args = command_parts[1:] if len(command_parts) > 1 else []
        explicit_args = self.args or []
        return parsed_args + explicit_args


class StreamableHTTPServerConfig(MCPServerConfig):
    """Configuration for StreamableHTTP-based MCP servers."""

    type: Literal["streamable_http"] = "streamable_http"
    url: str
    headers: dict[str, str] | None = None


class SSEServerConfig(MCPServerConfig):
    """Configuration for SSE-based MCP servers."""

    type: Literal["sse"] = "sse"
    url: str
    headers: dict[str, str] | None = None


# Discriminated union for different server config types
ServerConfigUnion = Annotated[
    StdioServerConfig | StreamableHTTPServerConfig | SSEServerConfig, Field(discriminator="type")
]


class MCPServersConfig(BaseModel):
    """Configuration for multiple MCP servers."""

    servers: dict[str, ServerConfigUnion] = Field(alias="mcpServers")

    @field_validator("servers", mode="before")
    @classmethod
    def infer_server_types(cls, servers_data: dict[str, Any]) -> dict[str, Any]:
        """Automatically infer server types when 'type' field is omitted."""

        for server_config in servers_data.values():
            if isinstance(server_config, dict) and "type" not in server_config:
                # Infer type based on distinguishing fields
                if "command" in server_config:
                    server_config["type"] = "stdio"
                elif "url" in server_config:
                    # Could infer SSE vs streamable_http based on URL patterns in the future
                    server_config["type"] = "streamable_http"

        return servers_data

    @classmethod
    def from_file(cls, config_path: Path, use_pyyaml: bool = False) -> "MCPServersConfig":
        """Load configuration from a JSON or YAML file.

        Args:
            config_path: Path to the configuration file
            use_pyyaml: If True, force use of PyYAML parser. Defaults to False.
                        Also automatically used for .yaml/.yml files.
        """
        with open(config_path) as config_file:
            # Check if YAML parsing is requested
            should_use_yaml = use_pyyaml or config_path.suffix.lower() in (".yaml", ".yml")

            if should_use_yaml:
                if not yaml:
                    raise ImportError("PyYAML is required to parse YAML files. ")
                return cls.model_validate(yaml.safe_load(config_file))
            else:
                return cls.model_validate(json.load(config_file))
