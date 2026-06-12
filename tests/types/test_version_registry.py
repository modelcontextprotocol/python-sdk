"""Pin the version registry and the per-version method tables.

The four tables exported by ``mcp.types.wire`` record, for each known
protocol version, which JSON-RPC method strings exist in that version's
schema, split by direction and message kind. They are hand-maintained
literals, so they are pinned three ways here: registry/shape invariants,
per-method anchor facts taken from the published schemas, and full equality
against the method sets derived from the committed version packages and from
the generated spec oracles (equality, not subset — a silently omitted method
must fail).
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from types import ModuleType
from typing import get_args

import pytest

import mcp.shared.version
from mcp.types import DEFAULT_NEGOTIATED_VERSION, LATEST_PROTOCOL_VERSION, wire

_TABLES: dict[str, Mapping[str, frozenset[str]]] = {
    "client requests": wire.CLIENT_REQUEST_METHODS,
    "client notifications": wire.CLIENT_NOTIFICATION_METHODS,
    "server requests": wire.SERVER_REQUEST_METHODS,
    "server notifications": wire.SERVER_NOTIFICATION_METHODS,
}

# The direction union each table corresponds to in the version packages and
# the spec oracles.
_UNION_NAMES: dict[str, str] = {
    "client requests": "ClientRequest",
    "client notifications": "ClientNotification",
    "server requests": "ServerRequest",
    "server notifications": "ServerNotification",
}

_PACKAGES: dict[str, str] = {
    "2024-11-05": "v2024_11_05",
    "2025-03-26": "v2025_03_26",
    "2025-06-18": "v2025_06_18",
    "2025-11-25": "v2025_11_25",
    "2026-07-28": "v2026_07_28",
}

# The 2025-11-25 schema defines four task request methods; the SDK models the
# task types but never dispatches them, so the tables exclude exactly these
# methods (and nothing else) from what the schema unions define.
_EXCLUDED_TASK_REQUEST_METHODS = frozenset({"tasks/get", "tasks/cancel", "tasks/result", "tasks/list"})

_RELEASED = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
_ALL = _RELEASED + ("2026-07-28",)


def test_registry_is_the_shared_version_registry() -> None:
    """The boundary re-exports the SDK's single version registry."""
    assert wire.KNOWN_PROTOCOL_VERSIONS is mcp.shared.version.KNOWN_PROTOCOL_VERSIONS


def test_registry_lists_known_versions_oldest_to_newest() -> None:
    assert wire.KNOWN_PROTOCOL_VERSIONS == _ALL


def test_negotiation_constants_are_registered_versions() -> None:
    """The negotiation constants name protocol revisions the registry knows."""
    assert LATEST_PROTOCOL_VERSION in wire.KNOWN_PROTOCOL_VERSIONS
    assert DEFAULT_NEGOTIATED_VERSION in wire.KNOWN_PROTOCOL_VERSIONS


@pytest.mark.parametrize("table_name", sorted(_TABLES))
def test_tables_are_keyed_by_the_registry_in_order(table_name: str) -> None:
    assert tuple(_TABLES[table_name]) == wire.KNOWN_PROTOCOL_VERSIONS


# Per-method anchor facts, each row: (method, table, versions where defined).
# Sources: the published schema unions; 2026-07-28 removed the lifecycle
# handshake, logging/setLevel, the resources subscribe pair, the roots
# methods, and the entire server -> client request channel, and added
# server/discover, subscriptions/listen, and
# notifications/subscriptions/acknowledged.
_ANCHORS: list[tuple[str, str, tuple[str, ...]]] = [
    ("initialize", "client requests", _RELEASED),
    ("notifications/initialized", "client notifications", _RELEASED),
    ("ping", "client requests", _RELEASED),
    ("ping", "server requests", _RELEASED),
    ("logging/setLevel", "client requests", _RELEASED),
    ("resources/subscribe", "client requests", _RELEASED),
    ("resources/unsubscribe", "client requests", _RELEASED),
    ("server/discover", "client requests", ("2026-07-28",)),
    ("subscriptions/listen", "client requests", ("2026-07-28",)),
    ("tools/list", "client requests", _ALL),
    ("tools/call", "client requests", _ALL),
    ("prompts/list", "client requests", _ALL),
    ("prompts/get", "client requests", _ALL),
    ("resources/list", "client requests", _ALL),
    ("resources/templates/list", "client requests", _ALL),
    ("resources/read", "client requests", _ALL),
    ("completion/complete", "client requests", _ALL),
    # elicitation/create entered the schema in 2025-06-18 and left with the
    # whole server -> client request channel in 2026-07-28.
    ("elicitation/create", "server requests", ("2025-06-18", "2025-11-25")),
    ("sampling/createMessage", "server requests", _RELEASED),
    ("roots/list", "server requests", _RELEASED),
    ("notifications/roots/list_changed", "client notifications", _RELEASED),
    ("notifications/elicitation/complete", "server notifications", ("2025-11-25", "2026-07-28")),
    ("notifications/subscriptions/acknowledged", "server notifications", ("2026-07-28",)),
    # notifications/tasks/status is a 2025-11-25 schema fact in both
    # directions; it stays in the tables even though the SDK's notification
    # unions exclude its type.
    ("notifications/tasks/status", "client notifications", ("2025-11-25",)),
    ("notifications/tasks/status", "server notifications", ("2025-11-25",)),
    ("notifications/progress", "client notifications", _ALL),
    ("notifications/progress", "server notifications", _ALL),
    ("notifications/cancelled", "client notifications", _ALL),
    ("notifications/cancelled", "server notifications", _ALL),
    ("notifications/message", "server notifications", _ALL),
]


@pytest.mark.parametrize(("method", "table_name", "versions"), _ANCHORS)
def test_method_membership_anchor(method: str, table_name: str, versions: tuple[str, ...]) -> None:
    """A method appears in its table at exactly the versions defining it."""
    table = _TABLES[table_name]
    for version in wire.KNOWN_PROTOCOL_VERSIONS:
        assert (method in table[version]) == (version in versions), f"{method} at {version}"


def test_no_task_request_method_in_any_table() -> None:
    """The four 2025-11-25 task request methods are excluded everywhere."""
    for table in _TABLES.values():
        for methods in table.values():
            assert not (methods & _EXCLUDED_TASK_REQUEST_METHODS)


def test_no_server_requests_at_2026_07_28() -> None:
    """2026-07-28 removed the standalone server -> client request channel."""
    assert wire.SERVER_REQUEST_METHODS["2026-07-28"] == frozenset()


def _union_methods(module: ModuleType, union_name: str) -> frozenset[str]:
    """The method literals of a direction union's arms.

    Empty when the module does not define the union (the 2026-07-28 schema
    has no server -> client requests, so it exports no ServerRequest union).
    """
    union = getattr(module, union_name, None)
    if union is None:
        return frozenset()
    methods: set[str] = set()
    for arm in get_args(union):
        (literal,) = get_args(arm.model_fields["method"].annotation)
        methods.add(literal)
    return frozenset(methods)


@pytest.mark.parametrize("version", _ALL)
@pytest.mark.parametrize("table_name", sorted(_TABLES))
def test_table_equals_version_package_union_methods(table_name: str, version: str) -> None:
    """Each table entry equals the method set derived from the committed
    version package's direction union, minus the task request methods."""
    package = importlib.import_module(f"mcp.types.{_PACKAGES[version]}")
    derived = _union_methods(package, _UNION_NAMES[table_name]) - _EXCLUDED_TASK_REQUEST_METHODS
    assert _TABLES[table_name][version] == derived


@pytest.mark.parametrize("version", _ALL)
@pytest.mark.parametrize("table_name", sorted(_TABLES))
def test_table_equals_spec_oracle_union_methods(table_name: str, version: str) -> None:
    """Each table entry equals the method set derived from the generated spec
    oracle's direction union, minus the task request methods."""
    oracle = importlib.import_module(f"tests.spec_oracles.{_PACKAGES[version]}")
    derived = _union_methods(oracle, _UNION_NAMES[table_name]) - _EXCLUDED_TASK_REQUEST_METHODS
    assert _TABLES[table_name][version] == derived
