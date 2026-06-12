"""Per-version method tables for the MCP wire protocol.

For each known protocol version (see ``mcp.shared.version.KNOWN_PROTOCOL_VERSIONS``),
these tables record which JSON-RPC method strings exist in that version's
schema, split by direction and message kind. They are plain data: nothing here
parses, validates, or dispatches.

Derivation rule, applied per version: the ``method`` literals of the request
and notification types reachable from that version's published schema unions,
minus the four 2025-11-25 ``tasks/*`` request methods (the SDK defines the
task types but never dispatches them), plus nothing. The
2025-11-25 ``notifications/tasks/status`` method is a schema fact and stays
listed even though the SDK's notification unions exclude its type.
"""

from collections.abc import Mapping
from typing import Final

# 2024-11-05
_CLIENT_REQUESTS_2024_11_05: Final[frozenset[str]] = frozenset(
    {
        "completion/complete",
        "initialize",
        "logging/setLevel",
        "ping",
        "prompts/get",
        "prompts/list",
        "resources/list",
        "resources/read",
        "resources/subscribe",
        "resources/templates/list",
        "resources/unsubscribe",
        "tools/call",
        "tools/list",
    }
)
_CLIENT_NOTIFICATIONS_2024_11_05: Final[frozenset[str]] = frozenset(
    {
        "notifications/cancelled",
        "notifications/initialized",
        "notifications/progress",
        "notifications/roots/list_changed",
    }
)
_SERVER_REQUESTS_2024_11_05: Final[frozenset[str]] = frozenset(
    {
        "ping",
        "roots/list",
        "sampling/createMessage",
    }
)
_SERVER_NOTIFICATIONS_2024_11_05: Final[frozenset[str]] = frozenset(
    {
        "notifications/cancelled",
        "notifications/message",
        "notifications/progress",
        "notifications/prompts/list_changed",
        "notifications/resources/list_changed",
        "notifications/resources/updated",
        "notifications/tools/list_changed",
    }
)

# 2025-03-26: identical method sets to 2024-11-05 (the revision changed type
# shapes, not the method surface).
_CLIENT_REQUESTS_2025_03_26: Final[frozenset[str]] = _CLIENT_REQUESTS_2024_11_05
_CLIENT_NOTIFICATIONS_2025_03_26: Final[frozenset[str]] = _CLIENT_NOTIFICATIONS_2024_11_05
_SERVER_REQUESTS_2025_03_26: Final[frozenset[str]] = _SERVER_REQUESTS_2024_11_05
_SERVER_NOTIFICATIONS_2025_03_26: Final[frozenset[str]] = _SERVER_NOTIFICATIONS_2024_11_05

# 2025-06-18: adds elicitation/create (server -> client).
_CLIENT_REQUESTS_2025_06_18: Final[frozenset[str]] = _CLIENT_REQUESTS_2024_11_05
_CLIENT_NOTIFICATIONS_2025_06_18: Final[frozenset[str]] = _CLIENT_NOTIFICATIONS_2024_11_05
_SERVER_REQUESTS_2025_06_18: Final[frozenset[str]] = _SERVER_REQUESTS_2024_11_05 | {"elicitation/create"}
_SERVER_NOTIFICATIONS_2025_06_18: Final[frozenset[str]] = _SERVER_NOTIFICATIONS_2024_11_05

# 2025-11-25: adds notifications/tasks/status (both directions) and
# notifications/elicitation/complete (server -> client). The four tasks/*
# request methods the schema also adds are excluded per the derivation rule.
_CLIENT_REQUESTS_2025_11_25: Final[frozenset[str]] = _CLIENT_REQUESTS_2024_11_05
_CLIENT_NOTIFICATIONS_2025_11_25: Final[frozenset[str]] = _CLIENT_NOTIFICATIONS_2024_11_05 | {
    "notifications/tasks/status",
}
_SERVER_REQUESTS_2025_11_25: Final[frozenset[str]] = _SERVER_REQUESTS_2025_06_18
_SERVER_NOTIFICATIONS_2025_11_25: Final[frozenset[str]] = _SERVER_NOTIFICATIONS_2024_11_05 | {
    "notifications/elicitation/complete",
    "notifications/tasks/status",
}

# 2026-07-28: removes the lifecycle handshake (initialize, ping,
# notifications/initialized), logging/setLevel, the resources subscribe pair,
# the roots and tasks methods, and the entire server -> client request
# channel; adds server/discover, subscriptions/listen, and
# notifications/subscriptions/acknowledged.
_CLIENT_REQUESTS_2026_07_28: Final[frozenset[str]] = frozenset(
    {
        "completion/complete",
        "prompts/get",
        "prompts/list",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "server/discover",
        "subscriptions/listen",
        "tools/call",
        "tools/list",
    }
)
_CLIENT_NOTIFICATIONS_2026_07_28: Final[frozenset[str]] = frozenset(
    {
        "notifications/cancelled",
        "notifications/progress",
    }
)
_SERVER_REQUESTS_2026_07_28: Final[frozenset[str]] = frozenset()
_SERVER_NOTIFICATIONS_2026_07_28: Final[frozenset[str]] = frozenset(
    {
        "notifications/cancelled",
        "notifications/elicitation/complete",
        "notifications/message",
        "notifications/progress",
        "notifications/prompts/list_changed",
        "notifications/resources/list_changed",
        "notifications/resources/updated",
        "notifications/subscriptions/acknowledged",
        "notifications/tools/list_changed",
    }
)

CLIENT_REQUEST_METHODS: Final[Mapping[str, frozenset[str]]] = {
    "2024-11-05": _CLIENT_REQUESTS_2024_11_05,
    "2025-03-26": _CLIENT_REQUESTS_2025_03_26,
    "2025-06-18": _CLIENT_REQUESTS_2025_06_18,
    "2025-11-25": _CLIENT_REQUESTS_2025_11_25,
    "2026-07-28": _CLIENT_REQUESTS_2026_07_28,
}
"""Client-to-server request methods defined at each protocol version."""

CLIENT_NOTIFICATION_METHODS: Final[Mapping[str, frozenset[str]]] = {
    "2024-11-05": _CLIENT_NOTIFICATIONS_2024_11_05,
    "2025-03-26": _CLIENT_NOTIFICATIONS_2025_03_26,
    "2025-06-18": _CLIENT_NOTIFICATIONS_2025_06_18,
    "2025-11-25": _CLIENT_NOTIFICATIONS_2025_11_25,
    "2026-07-28": _CLIENT_NOTIFICATIONS_2026_07_28,
}
"""Client-to-server notification methods defined at each protocol version."""

SERVER_REQUEST_METHODS: Final[Mapping[str, frozenset[str]]] = {
    "2024-11-05": _SERVER_REQUESTS_2024_11_05,
    "2025-03-26": _SERVER_REQUESTS_2025_03_26,
    "2025-06-18": _SERVER_REQUESTS_2025_06_18,
    "2025-11-25": _SERVER_REQUESTS_2025_11_25,
    "2026-07-28": _SERVER_REQUESTS_2026_07_28,
}
"""Server-to-client request methods defined at each protocol version."""

SERVER_NOTIFICATION_METHODS: Final[Mapping[str, frozenset[str]]] = {
    "2024-11-05": _SERVER_NOTIFICATIONS_2024_11_05,
    "2025-03-26": _SERVER_NOTIFICATIONS_2025_03_26,
    "2025-06-18": _SERVER_NOTIFICATIONS_2025_06_18,
    "2025-11-25": _SERVER_NOTIFICATIONS_2025_11_25,
    "2026-07-28": _SERVER_NOTIFICATIONS_2026_07_28,
}
"""Server-to-client notification methods defined at each protocol version."""
