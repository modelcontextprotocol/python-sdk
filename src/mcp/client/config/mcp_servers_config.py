"""Configuration management for MCP servers."""

# stdlib imports
import json
from pathlib import Path
from typing import Annotated, Any, Literal

# third party imports
from pydantic import BaseModel, Field, model_validator


class MCPServerConfig(BaseModel):
    """Base class for MCP server configurations."""

    pass


class StdioServerConfig(MCPServerConfig):
    """Configuration for stdio-based MCP servers."""

    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] | None = None
    env: dict[str, str] | None = None


class StreamableHttpConfig(MCPServerConfig):
    """Configuration for StreamableHTTP-based MCP servers."""

    type: Literal["streamable_http"] = "streamable_http"
    url: str
    headers: dict[str, str] | None = None


# Discriminated union for different server config types
ServerConfigUnion = Annotated[StdioServerConfig | StreamableHttpConfig, Field(discriminator="type")]


class MCPServersConfig(BaseModel):
    """Configuration for multiple MCP servers."""

    servers: dict[str, ServerConfigUnion] = Field(alias="mcpServers")

    @model_validator(mode="before")
    @classmethod
    def infer_server_types(cls, data: Any) -> Any:
        """Automatically infer server types when 'type' field is omitted."""
        if isinstance(data, dict) and "mcpServers" in data:
            for _server_name, server_config in data["mcpServers"].items():  # type: ignore
                if isinstance(server_config, dict) and "type" not in server_config:
                    # Infer type based on distinguishing fields
                    if "command" in server_config:
                        server_config["type"] = "stdio"
                    elif "url" in server_config:
                        server_config["type"] = "streamable_http"
        return data

    @classmethod
    def from_file(cls, config_path: Path) -> "MCPServersConfig":
        """Load configuration from a JSON file."""
        with open(config_path) as config_file:
            return cls.model_validate(json.load(config_file))
