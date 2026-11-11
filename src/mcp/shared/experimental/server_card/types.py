"""Pydantic models for MCP Server Cards (SEP-2127).

WARNING: These APIs are experimental and may change without notice.

A Server Card is a static metadata document describing a remote MCP server —
its identity, transport endpoints, and supported protocol versions — that a
client can fetch before initialization. Cards are published at any URL and
advertised through an AI Catalog entry (see
``mcp.shared.experimental.ai_catalog``).

A Server Card describes remote connectivity only: it does not list primitives
(tools/resources/prompts), which remain subject to runtime listing.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from mcp_types import Icon
from mcp_types._types import MCPModel
from pydantic import Field, field_validator

#: Canonical ``$schema`` value for a Server Card document.
SERVER_CARD_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"

# Pinned to the Server Card schema name: a card referencing the registry
# ``server.schema.json`` is rejected.
_SCHEMA_URL_PATTERN = r"^https://static\.modelcontextprotocol\.io/schemas/v1/server-card\.schema\.json$"
_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
_URL_TEMPLATE_PATTERN = r"^(https?://[^\s]+|\{[a-zA-Z_][a-zA-Z0-9_]*\}[^\s]*)$"

# Reject version ranges/wildcards. Range operators (incl. ``||`` unions and the
# whitespace of hyphen ranges like ``1.0.0 - 2.0.0``) match anywhere; wildcard
# segments (``1.x``, ``1.*``) only count in the release part, so prereleases
# like ``1.0.0-x`` stay valid.
_VERSION_RANGE_OPERATOR_RE = re.compile(r"[\^~|]|[<>]=?|\s")
_VERSION_WILDCARD_SEGMENT_RE = re.compile(r"(?:^|\.)[xX*](?:\.|$)")


class Input(MCPModel):
    """A user-supplied or pre-set input value (header value or URL variable)."""

    description: str | None = None
    """Human-readable explanation of the input."""

    is_required: bool | None = None
    """Whether the input must be supplied for the connection to succeed."""

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


class KeyValueInput(Input):
    """A named input — used for HTTP headers — whose ``value`` may reference variables."""

    name: str
    """Name of the header."""

    variables: dict[str, Input] | None = None
    """Variables referenced by ``{curly_braces}`` identifiers in ``value``."""


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


class ServerCard(MCPModel):
    """A static metadata document describing a remote MCP server.

    Published at any URL and advertised through an AI Catalog for
    pre-connection discovery. Describes only identity, transport and protocol
    versions — never the primitive listings (tools/resources/prompts), which
    remain subject to runtime listing.
    """

    schema_uri: Annotated[str, Field(alias="$schema", pattern=_SCHEMA_URL_PATTERN)] = SERVER_CARD_SCHEMA_URL
    """The Server Card JSON Schema URI this document conforms to (the ``$schema`` key).

    Required by the schema, but ingestion is intentionally lenient: a document
    that omits ``$schema`` is accepted and defaulted to the current ``v1`` URL
    rather than rejected. When present it must match the ``v1`` Server Card schema.
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
