"""Sanity checks for the divergence map between SDK and schema names.

Every entry in ``mcp.types._spec_names`` is a reviewed decision; these checks
keep the map honest as the type surface evolves: renames must point at real
public symbols, SDK-only names must actually be exported, and reason codes
must stay machine-greppable.

The map is the review record; the per-version comparison machinery in
``tests/spec_oracles/`` keeps its own operational records (the harness
exemption tables and ``burndown_allowlist.json``). The cross-record checks at
the bottom assert the two agree where they overlap, so neither can drift away
from the other silently.
"""

import re

import mcp.types
import mcp.types.jsonrpc
from mcp.types._spec_names import SCHEMA_NOT_MODELED, SDK_ONLY_NAMES, SDK_TO_SCHEMA_RENAMES
from tests.spec_oracles._harness import SDK_MACHINERY, load_allowlist

REASON_CODE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def test_every_renamed_sdk_name_is_a_real_public_symbol():
    for sdk_name, schema_name in SDK_TO_SCHEMA_RENAMES.items():
        assert hasattr(mcp.types, sdk_name) or hasattr(mcp.types.jsonrpc, sdk_name)
        assert schema_name and schema_name != sdk_name


def test_not_modeled_entries_carry_kebab_case_reason_codes():
    for schema_name, reason in SCHEMA_NOT_MODELED.items():
        assert schema_name
        assert REASON_CODE.fullmatch(reason), f"{schema_name}: reason code {reason!r} is not kebab-case"


def test_sdk_only_names_are_exported():
    missing = SDK_ONLY_NAMES - set(mcp.types.__all__)
    assert missing == set(), f"SDK-only names not in mcp.types.__all__: {sorted(missing)}"


def test_rename_keys_and_sdk_only_names_are_disjoint():
    assert SDK_ONLY_NAMES.isdisjoint(SDK_TO_SCHEMA_RENAMES)


def test_rename_schema_names_are_unique():
    """The burn-down harness inverts the rename map; duplicate schema names would collide."""
    schema_names = list(SDK_TO_SCHEMA_RENAMES.values())
    assert len(schema_names) == len(set(schema_names))


def test_not_modeled_entries_agree_with_the_burndown_allowlist():
    """SCHEMA_NOT_MODELED and the allowlisted missing-type findings name the same decisions.

    Forward: a deliberately-unmodeled schema export must carry a reviewed
    reason code here. Backward: an entry here must still be live in the
    comparison — either it fires (and is allowlisted) as a missing type, or
    its name is recycled onto a different SDK shape, in which case the
    comparison pairs the two by name instead of reporting a missing type.
    """
    deliberately_missing = {
        entry.name
        for entry in load_allowlist()
        if entry.check == "SPEC-TYPE-MISSING" and entry.category == "deliberate-deviation"
    }
    assert deliberately_missing <= set(SCHEMA_NOT_MODELED)
    for schema_name in set(SCHEMA_NOT_MODELED) - deliberately_missing:
        assert hasattr(mcp.types, schema_name) or hasattr(mcp.types.jsonrpc, schema_name), (
            f"{schema_name}: not allowlisted as a missing type and not a recycled SDK name - stale entry?"
        )


def test_sdk_only_names_agree_with_the_burndown_records():
    """Every SDK-only name is one the burn-down also treats as schema-less.

    A name pairs with no schema def in any version exactly when the burn-down
    either exempts it as machinery or carries it as an allowlisted
    no-schema-counterpart finding. If a future schema revision adopts one of
    these names, the corresponding allowlist entry goes stale, the burn-down
    gate fails, and both records get updated together.
    """
    phantom_names = {entry.name for entry in load_allowlist() if entry.check == "SDK-TYPE-PHANTOM"}
    unacknowledged = SDK_ONLY_NAMES - (SDK_MACHINERY | phantom_names)
    assert unacknowledged == set()
