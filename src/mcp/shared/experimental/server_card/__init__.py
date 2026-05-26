"""MCP Server Cards (SEP-2127) — shared types.

WARNING: These APIs are experimental and may change without notice.

A Server Card is a static metadata document describing a remote MCP server,
suitable for pre-connection discovery. See
``mcp.shared.experimental.server_card.types`` for the model definitions.

* Servers generate and serve a card with ``mcp.server.experimental.server_card``.
* Clients ingest one with ``mcp.client.experimental.server_card``.
"""

from mcp.shared.experimental.server_card.types import (
    SERVER_CARD_SCHEMA_URL,
    SERVER_SCHEMA_URL,
    WELL_KNOWN_PATH,
    Argument,
    Icon,
    Input,
    InputWithVariables,
    KeyValueInput,
    NamedArgument,
    Package,
    PackageTransport,
    PositionalArgument,
    Remote,
    Repository,
    Server,
    ServerCard,
    SsePackageTransport,
    StdioTransport,
    StreamableHttpPackageTransport,
)

__all__ = [
    "SERVER_CARD_SCHEMA_URL",
    "SERVER_SCHEMA_URL",
    "WELL_KNOWN_PATH",
    "Argument",
    "Icon",
    "Input",
    "InputWithVariables",
    "KeyValueInput",
    "NamedArgument",
    "Package",
    "PackageTransport",
    "PositionalArgument",
    "Remote",
    "Repository",
    "Server",
    "ServerCard",
    "SsePackageTransport",
    "StdioTransport",
    "StreamableHttpPackageTransport",
]
