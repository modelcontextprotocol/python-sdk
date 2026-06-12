"""Version registry, surface map, and per-version method-table invariants.

The registry is the ordered tuple of protocol versions the type layer knows;
the surface map sends every version to one of the two wire-surface fact
blocks; the method tables in `mcp.types.wire` state which wire methods exist
at each version in each direction. Anchor tests pin the load-bearing
per-version membership facts; equality tests pin each table to the generated
spec oracles (pinned at spec commit 6d441518), so no method can be silently
added or dropped.
"""

from types import ModuleType
from typing import Any, get_args, get_type_hints

import pytest

import mcp.shared.version
from mcp.types import _version_facts, wire
from mcp.types._version_facts import SURFACE_FACTS
from tests.spec_oracles import v2024_11_05, v2025_03_26, v2025_06_18, v2025_11_25, v2026_07_28

RELEASED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")

ORACLE_BY_VERSION: dict[str, ModuleType] = {
    "2024-11-05": v2024_11_05,
    "2025-03-26": v2025_03_26,
    "2025-06-18": v2025_06_18,
    "2025-11-25": v2025_11_25,
    "2026-07-28": v2026_07_28,
}

TASK_REQUEST_METHODS = frozenset({"tasks/cancel", "tasks/get", "tasks/list", "tasks/result"})
"""The 2025-11-25 task request methods the SDK deliberately never dispatches."""


def oracle_methods(oracle: ModuleType, union_name: str) -> frozenset[str]:
    """The `method` literal of every arm of an oracle request/notification union.

    Returns the empty set when the oracle has no such union (2026-07-28 defines
    no ServerRequest: the revision removed server-to-client requests).
    """
    union: Any = getattr(oracle, union_name, None)
    if union is None:
        return frozenset()
    methods: set[str] = set()
    for arm in get_args(union):
        (literal,) = get_args(get_type_hints(arm, include_extras=True)["method"])
        methods.add(literal)
    return frozenset(methods)


# --- registry ---


def test_registry_lists_the_known_versions_oldest_to_newest() -> None:
    assert wire.KNOWN_PROTOCOL_VERSIONS == (
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
        "2025-11-25",
        "2026-07-28",
    )


def test_registry_is_the_shared_module_tuple() -> None:
    """wire re-exports the one registry; there is no second copy to drift."""
    assert wire.KNOWN_PROTOCOL_VERSIONS is mcp.shared.version.KNOWN_PROTOCOL_VERSIONS


def test_surface_map_covers_exactly_the_known_versions_in_order() -> None:
    assert tuple(SURFACE_FACTS) == wire.KNOWN_PROTOCOL_VERSIONS


def test_versions_at_or_below_2025_11_25_share_one_surface_block() -> None:
    """Every version at or below 2025-11-25 maps to the same (empty) surface
    block; 2026-07-28 maps to its own. The two blocks are the only ones."""
    for version in RELEASED_VERSIONS:
        assert SURFACE_FACTS[version] is _version_facts.V2025_11_25
    assert SURFACE_FACTS["2026-07-28"] is _version_facts.V2026_07_28
    assert _version_facts.V2025_11_25 is not _version_facts.V2026_07_28


# --- method tables: anchors ---


def test_method_tables_cover_exactly_the_known_versions_in_order() -> None:
    for table in (
        wire.CLIENT_REQUEST_METHODS,
        wire.CLIENT_NOTIFICATION_METHODS,
        wire.SERVER_REQUEST_METHODS,
        wire.SERVER_NOTIFICATION_METHODS,
    ):
        assert tuple(table) == wire.KNOWN_PROTOCOL_VERSIONS


def test_lifecycle_and_subscription_methods_removed_at_2026_07_28() -> None:
    """initialize, ping, logging/setLevel, and the resources subscribe pair exist
    on every released version and are all removed in 2026-07-28."""
    removed_requests = {
        "initialize",
        "ping",
        "logging/setLevel",
        "resources/subscribe",
        "resources/unsubscribe",
    }
    for version in RELEASED_VERSIONS:
        assert removed_requests <= wire.CLIENT_REQUEST_METHODS[version]
        assert "notifications/initialized" in wire.CLIENT_NOTIFICATION_METHODS[version]
    assert not removed_requests & wire.CLIENT_REQUEST_METHODS["2026-07-28"]
    assert "notifications/initialized" not in wire.CLIENT_NOTIFICATION_METHODS["2026-07-28"]


def test_discover_and_subscriptions_listen_exist_only_at_2026_07_28() -> None:
    for version in RELEASED_VERSIONS:
        assert "server/discover" not in wire.CLIENT_REQUEST_METHODS[version]
        assert "subscriptions/listen" not in wire.CLIENT_REQUEST_METHODS[version]
    assert "server/discover" in wire.CLIENT_REQUEST_METHODS["2026-07-28"]
    assert "subscriptions/listen" in wire.CLIENT_REQUEST_METHODS["2026-07-28"]


def test_core_request_methods_exist_at_every_version() -> None:
    core = {
        "completion/complete",
        "prompts/get",
        "prompts/list",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "tools/call",
        "tools/list",
    }
    for version in wire.KNOWN_PROTOCOL_VERSIONS:
        assert core <= wire.CLIENT_REQUEST_METHODS[version]


def test_elicitation_create_is_a_server_request_on_2025_06_18_and_2025_11_25_only() -> None:
    assert "elicitation/create" not in wire.SERVER_REQUEST_METHODS["2024-11-05"]
    assert "elicitation/create" not in wire.SERVER_REQUEST_METHODS["2025-03-26"]
    assert "elicitation/create" in wire.SERVER_REQUEST_METHODS["2025-06-18"]
    assert "elicitation/create" in wire.SERVER_REQUEST_METHODS["2025-11-25"]
    assert "elicitation/create" not in wire.SERVER_REQUEST_METHODS["2026-07-28"]


def test_server_requests_removed_entirely_at_2026_07_28() -> None:
    """2026-07-28 removed the standalone server-to-client request channel."""
    for version in RELEASED_VERSIONS:
        assert {"ping", "roots/list", "sampling/createMessage"} <= wire.SERVER_REQUEST_METHODS[version]
    assert wire.SERVER_REQUEST_METHODS["2026-07-28"] == frozenset()


def test_elicitation_complete_notification_exists_from_2025_11_25() -> None:
    for version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        assert "notifications/elicitation/complete" not in wire.SERVER_NOTIFICATION_METHODS[version]
    assert "notifications/elicitation/complete" in wire.SERVER_NOTIFICATION_METHODS["2025-11-25"]
    assert "notifications/elicitation/complete" in wire.SERVER_NOTIFICATION_METHODS["2026-07-28"]


def test_subscriptions_acknowledged_notification_exists_only_at_2026_07_28() -> None:
    for version in RELEASED_VERSIONS:
        assert "notifications/subscriptions/acknowledged" not in wire.SERVER_NOTIFICATION_METHODS[version]
    assert "notifications/subscriptions/acknowledged" in wire.SERVER_NOTIFICATION_METHODS["2026-07-28"]


def test_roots_list_changed_notification_removed_at_2026_07_28() -> None:
    for version in RELEASED_VERSIONS:
        assert "notifications/roots/list_changed" in wire.CLIENT_NOTIFICATION_METHODS[version]
    assert "notifications/roots/list_changed" not in wire.CLIENT_NOTIFICATION_METHODS["2026-07-28"]


# --- method tables: equality ---


@pytest.mark.parametrize("version", SURFACE_FACTS)
def test_method_tables_equal_oracle_unions(version: str) -> None:
    """Equality, not subset: a silently omitted method must fail here."""
    oracle = ORACLE_BY_VERSION[version]
    assert wire.CLIENT_REQUEST_METHODS[version] == oracle_methods(oracle, "ClientRequest") - TASK_REQUEST_METHODS
    assert wire.CLIENT_NOTIFICATION_METHODS[version] == oracle_methods(oracle, "ClientNotification")
    assert wire.SERVER_REQUEST_METHODS[version] == oracle_methods(oracle, "ServerRequest") - TASK_REQUEST_METHODS
    assert wire.SERVER_NOTIFICATION_METHODS[version] == oracle_methods(oracle, "ServerNotification")


def test_wire_re_exports_the_fact_module_tables() -> None:
    """The boundary's public tables are the fact module's own objects; there is
    no second copy to drift."""
    assert wire.CLIENT_REQUEST_METHODS is _version_facts.CLIENT_REQUEST_METHODS
    assert wire.CLIENT_NOTIFICATION_METHODS is _version_facts.CLIENT_NOTIFICATION_METHODS
    assert wire.SERVER_REQUEST_METHODS is _version_facts.SERVER_REQUEST_METHODS
    assert wire.SERVER_NOTIFICATION_METHODS is _version_facts.SERVER_NOTIFICATION_METHODS
