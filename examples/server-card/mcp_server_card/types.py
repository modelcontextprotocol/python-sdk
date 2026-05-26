"""Pydantic models for MCP Server Cards (SEP-2127, experimental).

This is a 1:1 port of the TypeScript source of truth in
``experimental-ext-server-card/schema.ts``. It follows the conventions used by
the Python SDK's ``mcp.types`` module (camelCase JSON via ``to_camel`` alias
generator, ``populate_by_name`` so fields can be set by their Python names), and
reuses ``Icon`` / ``Implementation`` from the SDK rather than re-declaring them.

The module is deliberately shaped so it could be lifted into the SDK at
``mcp/experimental/server_card/types.py`` with no changes other than the import
of the shared ``MCPModel`` base.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.types import Icon  # reused: already exists in the core spec
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "SERVER_CARD_SCHEMA_URL",
    "SERVER_SCHEMA_URL",
    "Icon",
    "Input",
    "InputWithVariables",
    "KeyValueInput",
    "PositionalArgument",
    "NamedArgument",
    "Argument",
    "Repository",
    "Remote",
    "StdioTransport",
    "StreamableHttpPackageTransport",
    "SsePackageTransport",
    "PackageTransport",
    "Package",
    "ServerCard",
    "Server",
]

#: Canonical ``$schema`` value for a Server Card document.
SERVER_CARD_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"
#: Canonical ``$schema`` value for a registry-shaped Server document.
SERVER_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/v1/server.schema.json"

# Constraints copied verbatim from schema.ts JSDoc annotations.
_SCHEMA_URL_PATTERN = r"^https://static\.modelcontextprotocol\.io/schemas/v1/[^/]+\.schema\.json$"
_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
_URL_TEMPLATE_PATTERN = r"^(https?://[^\s]+|\{[a-zA-Z_][a-zA-Z0-9_]*\}[^\s]*)$"
_SHA256_PATTERN = r"^[a-f0-9]{64}$"


class _CardModel(BaseModel):
    """Base for Server Card types.

    Identical configuration to the SDK's ``mcp.types._types.MCPModel`` so the
    JSON wire format matches the rest of the protocol (camelCase keys, settable
    by Python field name).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Input(_CardModel):
    """A user-supplied or pre-set input value (header value, env var, argument)."""

    description: str | None = None
    """Human-readable explanation of the input."""

    is_required: bool | None = None
    """Whether the input must be supplied for the server to run."""

    is_secret: bool | None = None
    """Whether the input is a secret value (password, token, ...)."""

    format: Literal["string", "number", "boolean", "filepath"] | None = None
    """Input format. ``"filepath"`` is a path on the user's filesystem."""

    default: str | None = None
    """Default value for the input."""

    placeholder: str | None = None
    """Placeholder shown during configuration."""

    value: str | None = None
    """Pre-set value. If set, end users should not be able to change it.

    ``{curly_braces}`` identifiers are replaced from ``variables``.
    """

    choices: list[str] | None = None
    """Allowed values. If provided, the user must select one."""


class InputWithVariables(Input):
    """An ``Input`` whose ``value`` may reference ``{curly_braces}`` variables."""

    variables: dict[str, Input] | None = None
    """Variables referenced by ``{curly_braces}`` identifiers in ``value``."""


class KeyValueInput(InputWithVariables):
    """A named input — used for environment variables and HTTP headers."""

    name: str
    """Name of the header or environment variable."""


class PositionalArgument(InputWithVariables):
    """A positional command-line input — inserted verbatim into the command line."""

    type: Literal["positional"] = "positional"

    value_hint: str | None = None
    """Label / value-hint identifying the argument in URL variable substitution."""

    is_repeated: bool | None = None
    """Whether the argument can be repeated multiple times."""


class NamedArgument(InputWithVariables):
    """A named command-line input — a ``--flag={value}`` parameter."""

    type: Literal["named"] = "named"

    name: str
    """The flag name, including any leading dashes (e.g. ``"--port"``)."""

    is_repeated: bool | None = None
    """Whether the argument can be repeated multiple times."""


Argument = Annotated[PositionalArgument | NamedArgument, Field(discriminator="type")]
"""A command-line argument supplied to a package's binary or runtime."""


class Repository(_CardModel):
    """Repository metadata for the MCP server source code."""

    url: str
    """Repository URL for browsing source and ``git clone``."""

    source: str
    """Hosting service identifier (e.g. ``"github"``)."""

    subfolder: str | None = None
    """Relative path from repo root to the server in a monorepo."""

    id: str | None = None
    """Stable repository identifier from the hosting service."""


class Remote(_CardModel):
    """Metadata for connecting to a remote (HTTP-based) MCP server endpoint."""

    type: Literal["streamable-http", "sse"]
    """The transport type for this remote endpoint."""

    url: Annotated[str, Field(pattern=_URL_TEMPLATE_PATTERN)]
    """URL template. ``{curly_braces}`` variables are substituted before connecting."""

    headers: list[KeyValueInput] | None = None
    """HTTP headers required or accepted when connecting."""

    variables: dict[str, Input] | None = None
    """Variables referenceable as ``{curly_braces}`` in ``url`` and header values."""

    supported_protocol_versions: list[str] | None = None
    """MCP protocol versions actively supported by this endpoint."""


class StdioTransport(_CardModel):
    """Stdio transport — the client launches the package as a subprocess."""

    type: Literal["stdio"] = "stdio"


class StreamableHttpPackageTransport(_CardModel):
    """Streamable-HTTP transport for a locally-runnable package."""

    type: Literal["streamable-http"] = "streamable-http"

    url: Annotated[str, Field(pattern=_URL_TEMPLATE_PATTERN)]
    """URL template for the streamable-http transport."""

    headers: list[KeyValueInput] | None = None
    """HTTP headers to include when connecting to the local endpoint."""


class SsePackageTransport(_CardModel):
    """Server-sent events (SSE) transport for a locally-runnable package."""

    type: Literal["sse"] = "sse"

    url: Annotated[str, Field(pattern=_URL_TEMPLATE_PATTERN)]
    """SSE endpoint URL template."""

    headers: list[KeyValueInput] | None = None
    """HTTP headers to include when connecting to the local endpoint."""


PackageTransport = Annotated[
    StdioTransport | StreamableHttpPackageTransport | SsePackageTransport,
    Field(discriminator="type"),
]
"""Transport protocol configuration for a locally-runnable package."""


class Package(_CardModel):
    """Metadata for installing and running a packaged MCP server locally."""

    registry_type: str
    """How to download the package (``"npm"``, ``"pypi"``, ``"oci"``, ...)."""

    identifier: str
    """Package name (for registries) or URL (for direct downloads)."""

    transport: PackageTransport
    """Transport configuration for invoking this package after installation."""

    registry_base_url: str | None = None
    """Base URL of the package registry."""

    version: Annotated[str, Field(min_length=1)] | None = None
    """Package version."""

    supported_protocol_versions: list[str] | None = None
    """MCP protocol versions actively supported by this package."""

    runtime_hint: str | None = None
    """Hint for the runtime to use (``"npx"``, ``"uvx"``, ``"docker"``, ...)."""

    runtime_arguments: list[Argument] | None = None
    """Arguments passed to the package's runtime command."""

    package_arguments: list[Argument] | None = None
    """Arguments passed to the package's binary."""

    environment_variables: list[KeyValueInput] | None = None
    """Environment variables to set when running the package."""

    file_sha256: Annotated[str, Field(pattern=_SHA256_PATTERN)] | None = None
    """SHA-256 of the package file. Required for MCPB packages."""


class ServerCard(_CardModel):
    """A static metadata document describing a remote MCP server.

    Suitable for publishing at ``/.well-known/mcp/server-card`` for
    pre-connection discovery. Describes only identity, transport and protocol
    versions — never the primitive listings (tools/resources/prompts), which
    remain subject to runtime listing.
    """

    schema_uri: Annotated[str, Field(alias="$schema", pattern=_SCHEMA_URL_PATTERN)] = SERVER_CARD_SCHEMA_URL
    """The Server Card JSON Schema URI this document conforms to (the ``$schema`` key)."""

    name: Annotated[str, Field(min_length=3, max_length=200, pattern=_NAME_PATTERN)]
    """Server name in reverse-DNS ``namespace/name`` format."""

    version: Annotated[str, Field(max_length=255)]
    """Server version. SHOULD follow semantic versioning; ranges are rejected."""

    description: Annotated[str, Field(min_length=1, max_length=100)]
    """Clear human-readable explanation of server functionality."""

    title: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    """Optional human-readable display name."""

    website_url: str | None = None
    """Optional URL to the server's homepage / documentation."""

    repository: Repository | None = None
    """Optional repository metadata for source inspection."""

    icons: list[Icon] | None = None
    """Optional set of sized icons for display in a UI."""

    remotes: list[Remote] | None = None
    """Metadata for making HTTP-based connections to this server."""

    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """Extension metadata using reverse-DNS namespacing (the ``_meta`` key)."""


class Server(ServerCard):
    """A superset of ``ServerCard`` that also describes locally-runnable packages.

    This is the shape used by the MCP Registry's ``server.json``. Typically
    published to a registry rather than served from a ``.well-known`` URI.
    """

    schema_uri: Annotated[str, Field(alias="$schema", pattern=_SCHEMA_URL_PATTERN)] = SERVER_SCHEMA_URL

    packages: list[Package] | None = None
    """Metadata for running and connecting to local instances of this server."""
