"""Registry and per-version method table pins.

The protocol-version registry and the four method tables are plain data
consumed by the wire boundary. Pinned here: the registry's ordering
invariants, spot anchors for when each method enters and leaves the protocol,
and full equality of every table against the request/notification unions of
the generated spec-oracle modules AND of the committed version modules — a
silently omitted method (or an invented one) fails both directions.
"""

import importlib
from collections.abc import Mapping
from types import ModuleType
from typing import Any, get_args

import pytest

import mcp.shared.version
from mcp.shared.version import KNOWN_PROTOCOL_VERSIONS
from mcp.types import wire
from tests.spec_oracles import v2024_11_05, v2025_03_26, v2025_06_18, v2025_11_25, v2026_07_28

_TABLES: dict[str, Mapping[str, frozenset[str]]] = {
    "client-requests": wire.CLIENT_REQUEST_METHODS,
    "client-notifications": wire.CLIENT_NOTIFICATION_METHODS,
    "server-requests": wire.SERVER_REQUEST_METHODS,
    "server-notifications": wire.SERVER_NOTIFICATION_METHODS,
}

_ORACLE_MODULES: dict[str, ModuleType] = {
    "2024-11-05": v2024_11_05,
    "2025-03-26": v2025_03_26,
    "2025-06-18": v2025_06_18,
    "2025-11-25": v2025_11_25,
    "2026-07-28": v2026_07_28,
}

_ORACLE_UNION_NAMES: dict[str, str] = {
    "client-requests": "ClientRequest",
    "client-notifications": "ClientNotification",
    "server-requests": "ServerRequest",
    "server-notifications": "ServerNotification",
}

_EXCLUDED_TASK_REQUEST_METHODS = frozenset({"tasks/cancel", "tasks/get", "tasks/list", "tasks/result"})
"""The four 2025-11-25 task request methods.

The SDK defines the task types but never dispatches these methods, so the
tables deliberately exclude them. `notifications/tasks/status` is an ordinary
schema fact and stays listed.
"""


def test_wire_reexports_the_shared_registry() -> None:
    """`mcp.types.wire.KNOWN_PROTOCOL_VERSIONS` is the canonical public access
    to the one registry; it must be the same object, not a copy."""
    assert wire.KNOWN_PROTOCOL_VERSIONS is mcp.shared.version.KNOWN_PROTOCOL_VERSIONS
    assert wire.KNOWN_PROTOCOL_VERSIONS == ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")


def test_registry_lists_each_version_once() -> None:
    """Registry position is the only ordering authority, so duplicates would
    make ordering ambiguous."""
    assert len(set(KNOWN_PROTOCOL_VERSIONS)) == len(KNOWN_PROTOCOL_VERSIONS)


@pytest.mark.parametrize("table_name", sorted(_TABLES))
def test_tables_cover_every_known_version_in_registry_order(table_name: str) -> None:
    """Each method table has exactly one entry per known version, oldest to
    newest, so a version lookup can never miss."""
    assert tuple(_TABLES[table_name]) == KNOWN_PROTOCOL_VERSIONS


_VERSIONS_BEFORE_2026_07_28 = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


@pytest.mark.parametrize(
    ("table_name", "method", "expected_versions"),
    [
        # Removed in 2026-07-28: the lifecycle handshake, logging/setLevel,
        # and the resources subscribe pair exist in every earlier revision.
        ("client-requests", "initialize", _VERSIONS_BEFORE_2026_07_28),
        ("client-notifications", "notifications/initialized", _VERSIONS_BEFORE_2026_07_28),
        ("client-requests", "ping", _VERSIONS_BEFORE_2026_07_28),
        ("server-requests", "ping", _VERSIONS_BEFORE_2026_07_28),
        ("client-requests", "logging/setLevel", _VERSIONS_BEFORE_2026_07_28),
        ("client-requests", "resources/subscribe", _VERSIONS_BEFORE_2026_07_28),
        ("client-requests", "resources/unsubscribe", _VERSIONS_BEFORE_2026_07_28),
        # Added in 2026-07-28.
        ("client-requests", "server/discover", ("2026-07-28",)),
        ("client-requests", "subscriptions/listen", ("2026-07-28",)),
        ("server-notifications", "notifications/subscriptions/acknowledged", ("2026-07-28",)),
        # Present in every revision.
        ("client-requests", "tools/list", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "tools/call", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "prompts/list", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "prompts/get", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "resources/list", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "resources/templates/list", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "resources/read", KNOWN_PROTOCOL_VERSIONS),
        ("client-requests", "completion/complete", KNOWN_PROTOCOL_VERSIONS),
        # Elicitation: the request exists in 2025-06-18 and 2025-11-25 (the
        # 2026-07-28 revision removed every server -> client request); the
        # completion notification was added in 2025-11-25 and survives.
        ("server-requests", "elicitation/create", ("2025-06-18", "2025-11-25")),
        ("server-notifications", "notifications/elicitation/complete", ("2025-11-25", "2026-07-28")),
        # Sampling and roots: server -> client traffic through 2025-11-25.
        ("server-requests", "sampling/createMessage", _VERSIONS_BEFORE_2026_07_28),
        ("server-requests", "roots/list", _VERSIONS_BEFORE_2026_07_28),
        ("client-notifications", "notifications/roots/list_changed", _VERSIONS_BEFORE_2026_07_28),
    ],
)
def test_method_version_windows(table_name: str, method: str, expected_versions: tuple[str, ...]) -> None:
    """Spot anchors for the revisions where each method exists, per the
    published schemas; a method outside its window classifies as unknown."""
    table = _TABLES[table_name]
    present = tuple(version for version in KNOWN_PROTOCOL_VERSIONS if method in table[version])
    assert present == expected_versions


def test_no_server_requests_at_2026_07_28() -> None:
    """The 2026-07-28 revision removed the server -> client request channel
    entirely."""
    assert wire.SERVER_REQUEST_METHODS["2026-07-28"] == frozenset()


def _union_method_literals(union: Any) -> frozenset[str]:
    """Collect the `method` literal of every arm of an oracle union.

    `None` means the union does not exist in that revision's schema (the
    2026-07-28 schema removed every server -> client request, so its oracle
    module defines no ServerRequest alias): no methods.
    """
    if union is None:
        return frozenset()
    methods: set[str] = set()
    for arm in get_args(union):
        (literal,) = get_args(arm.model_fields["method"].annotation)
        assert isinstance(literal, str)
        methods.add(literal)
    return frozenset(methods)


@pytest.mark.parametrize("table_name", sorted(_TABLES))
@pytest.mark.parametrize("version", KNOWN_PROTOCOL_VERSIONS)
def test_tables_equal_the_oracle_union_methods(version: str, table_name: str) -> None:
    """Full equality, both directions, against the generated oracle unions:
    a silently omitted method (or an invented one) fails here. The only
    deliberate difference is the four task request methods."""
    oracle_union = getattr(_ORACLE_MODULES[version], _ORACLE_UNION_NAMES[table_name], None)
    expected = _union_method_literals(oracle_union) - _EXCLUDED_TASK_REQUEST_METHODS
    assert _TABLES[table_name][version] == expected


@pytest.mark.parametrize("table_name", sorted(_TABLES))
@pytest.mark.parametrize("version", KNOWN_PROTOCOL_VERSIONS)
def test_tables_equal_the_version_module_union_methods(version: str, table_name: str) -> None:
    """Full equality, both directions, against the committed version modules'
    direction unions — the same sets the wire boundary validates emissions
    through. The only deliberate difference is the four task request
    methods."""
    module = importlib.import_module(f"mcp.types.v{version.replace('-', '_')}")
    union = getattr(module, _ORACLE_UNION_NAMES[table_name], None)
    expected = _union_method_literals(union) - _EXCLUDED_TASK_REQUEST_METHODS
    assert _TABLES[table_name][version] == expected
