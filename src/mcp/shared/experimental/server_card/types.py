"""Pydantic models for MCP Server Cards (SEP-2127).

WARNING: These APIs are experimental and may change without notice.

A Server Card is a static metadata document describing a remote MCP server —
its identity, transport endpoints, and supported protocol versions — so a
client can discover and connect to it before initialization. Cards are
published at any URL and advertised through an AI Catalog entry (see
``mcp.shared.experimental.ai_catalog``). The companion ``Server`` shape is a
strict superset that adds locally-runnable ``packages`` (the MCP Registry
``server.json`` shape).

These models mirror the protocol types in ``mcp.types`` (camelCase wire format,
``Icon`` reused from the core spec) and validate purely through Pydantic, like
the rest of the SDK.

See https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2127.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from mcp.types import Icon
from mcp.types._types import MCPModel

#: Canonical ``$schema`` value for a Server Card document.
SERVER_CARD_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"
#: Canonical ``$schema`` value for a registry-shaped Server document.
SERVER_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/v1/server.schema.json"

# Constraints copied verbatim from the schema source of truth.
_SCHEMA_URL_PATTERN = r"^https://static\.modelcontextprotocol\.io/schemas/v1/[^/]+\.schema\.json$"
_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
_URL_TEMPLATE_PATTERN = r"^(https?://[^\s]+|\{[a-zA-Z_][a-zA-Z0-9_]*\}[^\s]*)$"
_SHA256_PATTERN = r"^[a-f0-9]{64}$"

# Version strings that look like ranges/wildcards. The spec allows non-semantic
# versions but rejects ranges; this is the one constraint not expressible as a
# field pattern, so it is enforced with a validator. Range operators are
# rejected anywhere; wildcard segments (``1.x``, ``1.*``) only count in the
# release part, so semver prereleases like ``1.0.0-x`` stay valid.
_VERSION_RANGE_OPERATOR_RE = re.compile(r"[\^~]|[<>]=?")
_VERSION_WILDCARD_SEGMENT_RE = re.compile(r"(?:^|\.)[xX*](?:\.|$)")


class Input(MCPModel):
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
    """Pre-set value. ``{curly_braces}`` identifiers are replaced from ``variables``."""

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


class Repository(MCPModel):
    """Repository metadata for the MCP server source code."""

    url: str
    """Repository URL for browsing source and ``git clone``."""

    source: str
    """Hosting service identifier (e.g. ``"github"``)."""

    subfolder: str | None = None
    """Relative path from repo root to the server in a monorepo."""

    id: str | None = None
    """Stable repository identifier from the hosting service."""


class Remote(MCPModel):
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


class StdioTransport(MCPModel):
    """Stdio transport — the client launches the package as a subprocess."""

    type: Literal["stdio"] = "stdio"


class StreamableHttpPackageTransport(MCPModel):
    """Streamable-HTTP transport for a locally-runnable package."""

    type: Literal["streamable-http"] = "streamable-http"

    url: Annotated[str, Field(pattern=_URL_TEMPLATE_PATTERN)]
    """URL template for the streamable-http transport."""

    headers: list[KeyValueInput] | None = None
    """HTTP headers to include when connecting to the local endpoint."""


class SsePackageTransport(MCPModel):
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


class Package(MCPModel):
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


class ServerCard(MCPModel):
    """A static metadata document describing a remote MCP server.

    Published at any URL and advertised through an AI Catalog for
    pre-connection discovery. Describes only identity, transport and protocol
    versions — never the primitive listings (tools/resources/prompts), which
    remain subject to runtime listing.
    """

    schema_uri: Annotated[str, Field(alias="$schema", pattern=_SCHEMA_URL_PATTERN)] = SERVER_CARD_SCHEMA_URL
    """The Server Card JSON Schema URI this document conforms to (the ``$schema`` key).

    The JSON Schema marks ``$schema`` as required; ingestion here is
    deliberately lenient and defaults it for documents that omit the key.
    """

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

    @field_validator("version")
    @classmethod
    def _reject_version_ranges(cls, value: str) -> str:
        release = value.split("-", 1)[0]
        if _VERSION_RANGE_OPERATOR_RE.search(value) or _VERSION_WILDCARD_SEGMENT_RE.search(release):
            raise ValueError(f"version must be an exact version, not a range/wildcard: {value!r}")
        return value


class Server(ServerCard):
    """A superset of ``ServerCard`` that also describes locally-runnable packages.

    This is the shape used by the MCP Registry's ``server.json``. Typically
    published to a registry rather than served by the server itself.
    """

    schema_uri: Annotated[str, Field(alias="$schema", pattern=_SCHEMA_URL_PATTERN)] = SERVER_SCHEMA_URL

    packages: list[Package] | None = None
    """Metadata for running and connecting to local instances of this server."""
