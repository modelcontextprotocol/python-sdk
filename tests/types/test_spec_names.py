"""The divergence map in `mcp.types._spec_names` is checked data, not prose.

Every claim the three tables make is asserted against the generated spec
oracles and the SDK namespace: renamed SDK names resolve and agree with the
oracle harness's own spec-to-SDK name map, deliberately-not-modeled schema
names are real definitions of at least one pinned schema version, and
SDK-only names are exported with no spec counterpart claimed elsewhere.
"""

import mcp.types
from mcp.types._spec_names import SCHEMA_NOT_MODELED, SDK_ONLY_NAMES, SDK_TO_SCHEMA_RENAMES
from tests.spec_oracles import _harness


def test_renamed_sdk_names_resolve() -> None:
    for sdk_name in SDK_TO_SCHEMA_RENAMES:
        assert _harness.sdk_lookup(sdk_name) is not None, f"renamed SDK name {sdk_name} does not resolve"


def test_rename_table_agrees_with_the_oracle_harness_name_map() -> None:
    """The burn-down harness carries its own spec-to-SDK name map (ported
    unchanged with the oracles); each rename recorded here must be the inverse
    of an entry there, so the two records cannot drift apart."""
    for sdk_name, schema_name in SDK_TO_SCHEMA_RENAMES.items():
        assert _harness.NAME_MAP.get(schema_name) == sdk_name, (
            f"{sdk_name} -> {schema_name} has no matching harness map entry"
        )


def test_harness_name_map_entries_are_recorded_dispositions() -> None:
    """The reverse direction of the drift check: every spec-to-SDK pairing the
    oracle harness carries is recorded in the divergence map — as the inverse
    of a rename, or as a deliberately-not-modeled schema name (the
    `RequestMetaObject` pairing, remodeled as the `RequestParamsMeta`
    TypedDict) — so a harness-only pairing cannot drift in unrecorded."""
    recorded = set(SDK_TO_SCHEMA_RENAMES.values()) | set(SCHEMA_NOT_MODELED)
    for schema_name in _harness.NAME_MAP:
        assert schema_name in recorded, f"{schema_name} pairing is not recorded in the divergence map"


def test_not_modeled_names_are_real_schema_definitions() -> None:
    """Every deliberately-not-modeled name exists in at least one pinned
    schema version's generated oracle — the table records decisions about real
    schema exports, not typos."""
    oracles = [_harness.oracle_module(name) for name in _harness.ORACLE_MODULES]
    for schema_name in SCHEMA_NOT_MODELED:
        assert any(hasattr(oracle, schema_name) for oracle in oracles), (
            f"{schema_name} appears in no generated oracle module"
        )


def test_sdk_only_names_are_exported() -> None:
    for name in SDK_ONLY_NAMES:
        assert name in mcp.types.__all__, f"SDK-only name {name} is not exported"


def test_a_name_appears_in_at_most_one_table() -> None:
    """Each SDK name has one disposition: renamed or SDK-only, never both."""
    assert not set(SDK_TO_SCHEMA_RENAMES) & SDK_ONLY_NAMES
