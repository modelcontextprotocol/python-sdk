"""Configuration management for MCP servers."""

# stdlib imports
import json
import os
import re
import shlex
from pathlib import Path
from typing import Annotated, Any, Literal, cast

# third party imports
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore
from pydantic import BaseModel, Field, field_validator, model_validator


class InputDefinition(BaseModel):
    """Definition of an input parameter."""

    type: Literal["promptString"] = "promptString"
    id: str
    description: str | None = None
    password: bool = False


class MCPServerConfig(BaseModel):
    """Base class for MCP server configurations."""

    def as_dict(self) -> dict[str, Any]:
        """Return the server configuration as a dictionary."""
        return self.model_dump(exclude_none=True)


class StdioServerConfig(MCPServerConfig):
    """Configuration for stdio-based MCP servers."""

    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] | None = None
    env: dict[str, str] | None = None

    def _parse_command(self) -> list[str]:
        """Parse the command string into parts, handling quotes properly.

        Strips unnecessary whitespace and newlines to handle YAML multi-line strings.
        Treats backslashes followed by newlines as line continuations.
        """
        # Handle backslash line continuations by removing them and the following newline
        cleaned_command = self.command.replace("\\\n", " ")
        # Then normalize all whitespace (including remaining newlines) to single spaces
        cleaned_command = " ".join(cleaned_command.split())
        return shlex.split(cleaned_command)

    @property
    def effective_command(self) -> str:
        """Get the effective command (first part of the command string)."""
        return self._parse_command()[0]

    @property
    def effective_args(self) -> list[str]:
        """Get the effective arguments (parsed from command plus explicit args)."""
        command_parts = self._parse_command()
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

    servers: dict[str, ServerConfigUnion]
    inputs: list[InputDefinition] | None = None

    @model_validator(mode="before")
    @classmethod
    def handle_field_aliases(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Handle both 'servers' and 'mcpServers' field names."""

        # If 'mcpServers' exists but 'servers' doesn't, use 'mcpServers'
        if "mcpServers" in data and "servers" not in data:
            data["servers"] = data["mcpServers"]
            del data["mcpServers"]
        # If both exist, prefer 'servers' and remove 'mcpServers'
        elif "mcpServers" in data and "servers" in data:
            del data["mcpServers"]

        return data

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

    def get_required_inputs(self) -> list[str]:
        """Get list of input IDs that are defined in the inputs section."""
        if not self.inputs:
            return []
        return [input_def.id for input_def in self.inputs]

    def validate_inputs(self, provided_inputs: dict[str, str]) -> list[str]:
        """Validate provided inputs against input definitions.

        Returns list of missing required input IDs.
        """
        if not self.inputs:
            return []

        required_input_ids = self.get_required_inputs()
        missing_inputs = [input_id for input_id in required_input_ids if input_id not in provided_inputs]

        return missing_inputs

    def get_input_description(self, input_id: str) -> str | None:
        """Get the description for a specific input ID."""
        if not self.inputs:
            return None

        for input_def in self.inputs:
            if input_def.id == input_id:
                return input_def.description

        return None

    @classmethod
    def _substitute_inputs(cls, data: Any, inputs: dict[str, str]) -> Any:
        """Recursively substitute ${input:key} placeholders with values from inputs dict."""
        if isinstance(data, str):
            # Replace ${input:key} patterns with values from inputs
            def replace_input(match: re.Match[str]) -> str:
                key = match.group(1)
                if key in inputs:
                    return inputs[key]
                else:
                    raise ValueError(f"Missing input value for key: '{key}'")

            return re.sub(r"\$\{input:([^}]+)\}", replace_input, data)

        elif isinstance(data, dict):
            dict_result: dict[str, Any] = {}
            dict_data = cast(dict[str, Any], data)
            for k, v in dict_data.items():
                dict_result[k] = cls._substitute_inputs(v, inputs)
            return dict_result

        elif isinstance(data, list):
            list_data = cast(list[Any], data)
            return [cls._substitute_inputs(item, inputs) for item in list_data]

        else:
            return data

    @classmethod
    def _strip_json_comments(cls, content: str) -> str:
        """Strip // comments from JSON content, being careful not to remove // inside strings."""
        result: list[str] = []
        lines = content.split("\n")

        for line in lines:
            # Track if we're inside a string
            in_string = False
            escaped = False
            comment_start = -1

            for i, char in enumerate(line):
                if escaped:
                    escaped = False
                    continue

                if char == "\\" and in_string:
                    escaped = True
                    continue

                if char == '"':
                    in_string = not in_string
                    continue

                # Look for // comment start when not in string
                if not in_string and char == "/" and i + 1 < len(line) and line[i + 1] == "/":
                    comment_start = i
                    break

            # If we found a comment, remove it
            if comment_start != -1:
                line = line[:comment_start].rstrip()

            result.append(line)

        return "\n".join(result)

    @classmethod
    def from_file(
        cls, config_path: Path | str, use_pyyaml: bool = False, inputs: dict[str, str] | None = None
    ) -> "MCPServersConfig":
        """Load configuration from a JSON or YAML file.

        Args:
            config_path: Path to the configuration file
            use_pyyaml: If True, force use of PyYAML parser. Defaults to False.
                        Also automatically used for .yaml/.yml files.
            inputs: Dictionary of input values to substitute for ${input:key} placeholders
        """

        config_path = os.path.expandvars(config_path)  # Expand environment variables like $HOME
        config_path = Path(config_path)  # Convert to Path object
        config_path = config_path.expanduser()  # Expand ~ to home directory

        with open(config_path) as config_file:
            content = config_file.read()

            # Check if YAML parsing is requested
            should_use_yaml = use_pyyaml or config_path.suffix.lower() in (".yaml", ".yml")

            if should_use_yaml:
                if not yaml:
                    raise ImportError("PyYAML is required to parse YAML files. ")
                data = yaml.safe_load(content)
            else:
                # Strip comments from JSON content (JSONC support)
                cleaned_content = cls._strip_json_comments(content)
                data = json.loads(cleaned_content)

            # Create a preliminary config to validate inputs if they're defined
            preliminary_config = cls.model_validate(data)

            # Validate inputs if provided and input definitions exist
            if inputs is not None and preliminary_config.inputs:
                missing_inputs = preliminary_config.validate_inputs(inputs)
                if missing_inputs:
                    descriptions: list[str] = []
                    for input_id in missing_inputs:
                        desc = preliminary_config.get_input_description(input_id)
                        descriptions.append(f"  - {input_id}: {desc or 'No description'}")

                    raise ValueError("Missing required input values:\n" + "\n".join(descriptions))

            # Substitute input placeholders if inputs provided
            if inputs:
                data = cls._substitute_inputs(data, inputs)

            return cls.model_validate(data)
