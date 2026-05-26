"""MCP Server Cards — example Python implementation (SEP-2127, experimental).

A small, self-contained library showing what Server Card support could look like
in the Python SDK. It mirrors the TypeScript source of truth in
``experimental-ext-server-card/schema.ts`` and follows the SDK's ``mcp.types``
conventions, so the library portion could be lifted into
``mcp/experimental/server_card/`` largely unchanged.

* **Clients** consume and validate a card:
  :func:`fetch_server_card`, :func:`load_server_card`, :func:`parse_server_card`.
* **Servers** generate a card and publish it:
  :func:`build_server_card`, :func:`write_server_card`, :func:`mount_server_card`,
  :func:`add_server_card_route`.
"""

from .client import WELL_KNOWN_PATH, fetch_server_card, load_server_card, well_known_url
from .server import (
    add_server_card_route,
    build_server_card,
    card_to_dict,
    card_to_json,
    mount_server_card,
    server_card_from_implementation,
    server_card_route,
    streamable_http_remote,
    write_server_card,
)
from .types import (
    SERVER_CARD_SCHEMA_URL,
    SERVER_SCHEMA_URL,
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
from .validation import (
    ServerCardValidationError,
    load_bundled_schema,
    parse_server,
    parse_server_card,
    validate_against_schema,
)

__all__ = [
    # types
    "SERVER_CARD_SCHEMA_URL",
    "SERVER_SCHEMA_URL",
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
    # client
    "WELL_KNOWN_PATH",
    "fetch_server_card",
    "load_server_card",
    "well_known_url",
    # server
    "add_server_card_route",
    "build_server_card",
    "card_to_dict",
    "card_to_json",
    "mount_server_card",
    "server_card_from_implementation",
    "server_card_route",
    "streamable_http_remote",
    "write_server_card",
    # validation
    "ServerCardValidationError",
    "load_bundled_schema",
    "parse_server",
    "parse_server_card",
    "validate_against_schema",
]
