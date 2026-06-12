"""Cross-check the per-version fact blocks against the generated spec oracles.

Each `VersionFacts` block in `mcp.types._version_facts` is hand-written; the
generated oracle module for the same protocol version (`tests/spec_oracles`,
pinned at spec commit 6d441518) is the machine-derived witness. These tests
re-derive each block's method sets from the oracle's request/notification
unions, check every strip/inject row against oracle field presence in both
directions, tie each refusal to the schema fact behind it, and re-derive the
two mandate scalars — so a hand-written block cannot silently drift from its
pinned schema.

One deliberate divergence: the 2025-11-25 schema defines four task request
methods (tasks/cancel, tasks/get, tasks/list, tasks/result) in both request
directions. The SDK keeps them out of its method tables and unions — the task
payload types are modeled for compatibility, but the methods are never
dispatched (tasks continue as a protocol extension) — so the derivation
subtracts them. notifications/tasks/status is not subtracted: it remains a
method fact of the 2025-11-25 schema.
"""

from types import ModuleType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, TypeAdapter

from mcp.types import (
    CreateMessageRequest,
    CreateMessageResultWithTools,
    InputRequiredResult,
)
from mcp.types._version_facts import (
    VERSION_FACTS,
    _elicit_list_values,
    _elicit_url_mode_params,
    _empty_input_required,
    _missing_request_id,
    _sampling_array_content,
    _sampling_tool_content,
)
from tests.spec_oracles import v2024_11_05, v2025_03_26, v2025_06_18, v2025_11_25, v2026_07_28
from tests.spec_oracles._harness import resolve_sdk_name, sdk_lookup, wire_fields

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


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_client_request_methods_match_oracle(version: str) -> None:
    expected = oracle_methods(ORACLE_BY_VERSION[version], "ClientRequest") - TASK_REQUEST_METHODS
    assert VERSION_FACTS[version].client_request_methods == expected


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_client_notification_methods_match_oracle(version: str) -> None:
    expected = oracle_methods(ORACLE_BY_VERSION[version], "ClientNotification")
    assert VERSION_FACTS[version].client_notification_methods == expected


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_server_request_methods_match_oracle(version: str) -> None:
    expected = oracle_methods(ORACLE_BY_VERSION[version], "ServerRequest") - TASK_REQUEST_METHODS
    assert VERSION_FACTS[version].server_request_methods == expected


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_server_notification_methods_match_oracle(version: str) -> None:
    expected = oracle_methods(ORACLE_BY_VERSION[version], "ServerNotification")
    assert VERSION_FACTS[version].server_notification_methods == expected


# ----------------------------------------------------------------------------
# Strip/inject rows vs oracle field presence.
#
# A strip row says "this wire field does not exist at this version"; an inject
# row says "this version's wire requires the field". Both are checkable
# against the generated oracle for the version: resolve the row's owner to its
# oracle definition(s) and look for the wire field. Rows on non-leaf monolith
# classes (Result, CacheableResult) have no oracle definition of their own at
# most versions, so resolution fans out to every oracle definition whose SDK
# counterpart subclasses the owner — the same isinstance reach the rows have
# at runtime. The check runs in both directions: a row may exist only where
# the oracle lacks the field, and a field present in the oracle forbids the
# row.
# ----------------------------------------------------------------------------

# Oracle definition name -> SDK class name, for capability sub-objects the
# schemas declare inline and the SDK names with a Capability suffix.
LIFTED_DEF_NAMES = {"Roots": "RootsCapability"}

# (version, owner class name, wire field) strip rows with no oracle definition
# to check against; each is pinned to the schema fact that explains the gap.
STRIP_ROWS_WITHOUT_ORACLE_DEFS = frozenset(
    {
        # The pre-2025-11-25 schemas declare request params inline on each
        # request definition (the generated oracles synthesize no named params
        # defs there), and elicitation does not exist before 2025-06-18. The
        # `task` field itself is 2025-11-25 only.
        ("2024-11-05", "CallToolRequestParams", "task"),
        ("2024-11-05", "CreateMessageRequestParams", "task"),
        ("2024-11-05", "ElicitRequestFormParams", "task"),
        ("2024-11-05", "ElicitRequestURLParams", "task"),
        ("2025-03-26", "CallToolRequestParams", "task"),
        ("2025-03-26", "CreateMessageRequestParams", "task"),
        ("2025-03-26", "ElicitRequestFormParams", "task"),
        ("2025-03-26", "ElicitRequestURLParams", "task"),
        ("2025-06-18", "CallToolRequestParams", "task"),
        ("2025-06-18", "CreateMessageRequestParams", "task"),
        ("2025-06-18", "ElicitRequestFormParams", "task"),
        ("2025-06-18", "ElicitRequestURLParams", "task"),
        # 2026-07-28 reduces the roots capability to an untyped empty object
        # with no named definition; `listChanged` was removed in that revision.
        ("2026-07-28", "RootsCapability", "listChanged"),
    }
)

# Oracle definitions that map to SDK Result subclasses but carry none of the
# shared 2026-07-28 result fields: the schema types them only as embedded
# input-response payloads (input-required flow), never as top-level results.
# Inject rows are top-level facts, so these definitions cannot witness them.
EMBEDDED_PAYLOAD_DEFS = frozenset({"CreateMessageResult", "ElicitResult", "ListRootsResult"})


def oracle_model_defs(oracle: ModuleType) -> dict[str, type[BaseModel]]:
    """Every model definition the oracle module itself declares."""
    return {
        name: obj
        for name, obj in vars(oracle).items()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == oracle.__name__
    }


def oracle_counterparts(version: str, owner: type[BaseModel]) -> dict[str, type[BaseModel]]:
    """The oracle definitions at `version` whose SDK counterpart is `owner` or a subclass."""
    oracle = ORACLE_BY_VERSION[version]
    oracle_key = oracle.__name__.rsplit(".", 1)[-1]
    counterparts: dict[str, type[BaseModel]] = {}
    for def_name, oracle_cls in oracle_model_defs(oracle).items():
        sdk_name = LIFTED_DEF_NAMES.get(def_name, resolve_sdk_name(oracle_key, def_name))
        sdk_obj = sdk_lookup(sdk_name)
        if isinstance(sdk_obj, type) and issubclass(sdk_obj, owner):
            counterparts[def_name] = oracle_cls
    return counterparts


ALL_STRIP_PAIRS = sorted(
    {(row.owner, row.wire_field) for facts in VERSION_FACTS.values() for row in facts.strip_on_emit},
    key=lambda pair: (pair[0].__name__, pair[1]),
)


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_strip_rows_match_oracle_field_presence(version: str) -> None:
    """A strip row exists exactly where the version's schema lacks the field."""
    rows_in_block = {(row.owner, row.wire_field) for row in VERSION_FACTS[version].strip_on_emit}
    for owner, wire_field in ALL_STRIP_PAIRS:
        row_present = (owner, wire_field) in rows_in_block
        counterparts = oracle_counterparts(version, owner)
        if not counterparts:
            assert not row_present or (version, owner.__name__, wire_field) in STRIP_ROWS_WITHOUT_ORACLE_DEFS, (
                f"unpinned strip row with no oracle definition: {owner.__name__}.{wire_field} at {version}"
            )
            continue
        field_in_schema = any(wire_field in wire_fields(oracle_cls) for oracle_cls in counterparts.values())
        assert row_present == (not field_in_schema), (
            f"{owner.__name__}.{wire_field} at {version}: row_present={row_present}, schema has field={field_in_schema}"
        )


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_inject_rows_match_oracle_fields(version: str) -> None:
    """Injected fields exist in the version's schema, are required there, and the
    injected defaults satisfy the oracle's field type."""
    for row in VERSION_FACTS[version].inject_on_emit:
        counterparts = oracle_counterparts(version, row.owner)
        assert counterparts, f"inject row {row.owner.__name__}.{row.wire_field} has no oracle definition at {version}"
        for def_name, oracle_cls in counterparts.items():
            if def_name in EMBEDDED_PAYLOAD_DEFS:
                assert row.wire_field not in wire_fields(oracle_cls)
                continue
            fields = wire_fields(oracle_cls)
            assert row.wire_field in fields, f"{def_name} lacks {row.wire_field} at {version}"
            assert fields[row.wire_field].is_required(), f"{def_name}.{row.wire_field} is optional at {version}"
            TypeAdapter(fields[row.wire_field].annotation).validate_python(row.value)


# ----------------------------------------------------------------------------
# Refuse rows vs the schema facts behind them. Each named predicate encodes
# one structural fact ("no tool content", "single-block content", ...); the
# oracle expresses the same fact through the presence/shape of a definition,
# so each row family is asserted in both directions per version.
# ----------------------------------------------------------------------------


def refusals_with(version: str, predicate: Any) -> list[Any]:
    return [row for row in VERSION_FACTS[version].refuse_on_emit if row.when is predicate]


def _admits_list(annotation: Any) -> bool:
    """Whether a (possibly union) annotation accepts a JSON array."""
    if get_origin(annotation) in (Union, UnionType):
        return any(_admits_list(arm) for arm in get_args(annotation))
    return get_origin(annotation) is list


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_input_required_type_refusal_matches_oracle(version: str) -> None:
    """The input-required result type is refused exactly where the schema lacks it."""
    type_refusals = [row for row in VERSION_FACTS[version].refuse_on_emit if row.when is None]
    schema_has_type = "InputRequiredResult" in oracle_model_defs(ORACLE_BY_VERSION[version])
    if schema_has_type:
        assert type_refusals == []
    else:
        assert [row.owner for row in type_refusals] == [InputRequiredResult]


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_tool_content_refusals_match_oracle(version: str) -> None:
    """Tool sampling content is refused exactly where the schema has no tool content types."""
    rows = refusals_with(version, _sampling_tool_content)
    schema_admits = "ToolUseContent" in oracle_model_defs(ORACLE_BY_VERSION[version])
    if schema_admits:
        assert rows == []
    else:
        assert {row.owner for row in rows} == {CreateMessageRequest, CreateMessageResultWithTools}


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_array_content_refusals_match_oracle(version: str) -> None:
    """Array sampling content is refused exactly where the schema types content as a single block."""
    rows = refusals_with(version, _sampling_array_content)
    oracle = ORACLE_BY_VERSION[version]
    content = wire_fields(oracle_model_defs(oracle)["SamplingMessage"])["content"]
    if _admits_list(content.annotation):
        assert rows == []
    else:
        assert {row.owner for row in rows} == {CreateMessageRequest, CreateMessageResultWithTools}


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_url_elicitation_refusals_match_oracle(version: str) -> None:
    """Url-mode elicitation is refused exactly where the schema has no url-mode params."""
    rows = refusals_with(version, _elicit_url_mode_params)
    schema_admits = "ElicitRequestURLParams" in oracle_model_defs(ORACLE_BY_VERSION[version])
    assert (rows == []) == schema_admits


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_multiselect_refusals_match_oracle(version: str) -> None:
    """List elicitation values are refused exactly where the schema admits no list values.

    Before 2025-06-18 the schema defines no ElicitResult at all, which equally
    means list values have no wire form there.
    """
    rows = refusals_with(version, _elicit_list_values)
    elicit_result = oracle_model_defs(ORACLE_BY_VERSION[version]).get("ElicitResult")
    schema_admits = False
    if elicit_result is not None:
        content = wire_fields(elicit_result)["content"].annotation
        # Unwrap dict[str, V] | None down to the value union V.
        value_unions = [
            get_args(arm)[1]
            for arm in (get_args(content) if get_origin(content) in (Union, UnionType) else (content,))
            if get_origin(arm) is dict
        ]
        schema_admits = any(_admits_list(value_union) for value_union in value_unions)
    assert (rows == []) == schema_admits


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_request_id_refusals_match_oracle(version: str) -> None:
    """An id-less cancellation is refused exactly where the schema requires requestId."""
    rows = refusals_with(version, _missing_request_id)
    params = oracle_model_defs(ORACLE_BY_VERSION[version])["CancelledNotification"].model_fields["params"].annotation
    assert isinstance(params, type) and issubclass(params, BaseModel)
    assert (rows != []) == wire_fields(params)["requestId"].is_required()


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_empty_input_required_refusal_matches_oracle(version: str) -> None:
    """The at-least-one-of check exists exactly where the schema defines the type.

    The 2026-07-28 schema requires at least one of inputRequests/requestState
    in prose only — both fields are optional in the schema — which is why the
    fact is an emission check and not model validation.
    """
    rows = refusals_with(version, _empty_input_required)
    schema_type = oracle_model_defs(ORACLE_BY_VERSION[version]).get("InputRequiredResult")
    if schema_type is None:
        assert rows == []
    else:
        assert [row.owner for row in rows] == [InputRequiredResult]
        assert not wire_fields(schema_type)["inputRequests"].is_required()
        assert not wire_fields(schema_type)["requestState"].is_required()


# ----------------------------------------------------------------------------
# Mandate scalars vs the oracle.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_meta_required_methods_match_oracle(version: str) -> None:
    """The required-_meta method set equals the requests whose params require the reserved keys.

    Only the 2026-07-28 schema defines RequestMetaObject (the params `_meta`
    shape carrying the required reserved keys), and it requires it on every
    client request: each arm's params declare a required RequestMetaObject
    `_meta`, asserted arm by arm. Every other version's set is empty.
    """
    oracle = ORACLE_BY_VERSION[version]
    request_meta = getattr(oracle, "RequestMetaObject", None)
    derived: set[str] = set()
    if request_meta is not None:
        for arm in get_args(oracle.ClientRequest):
            (method,) = get_args(get_type_hints(arm, include_extras=True)["method"])
            params = arm.model_fields["params"].annotation
            assert isinstance(params, type) and issubclass(params, BaseModel), f"{method} params must be a model"
            meta_field = wire_fields(params)["_meta"]
            assert meta_field.is_required() and meta_field.annotation is request_meta, (
                f"{method} params must require a RequestMetaObject _meta"
            )
            derived.add(method)
    assert VERSION_FACTS[version].meta_required_methods == frozenset(derived)


@pytest.mark.parametrize("version", VERSION_FACTS)
def test_recognized_result_types_match_oracle(version: str) -> None:
    """Recognized resultType values exist exactly where the schema defines ResultType.

    The 2026-07-28 schema types ResultType as an open string and names exactly
    two values, "complete" and "input_required", in its description; earlier
    schemas have no ResultType at all, so any inbound value parses there.
    """
    oracle = ORACLE_BY_VERSION[version]
    if hasattr(oracle, "ResultType"):
        assert oracle.ResultType is str
        assert VERSION_FACTS[version].recognized_result_types == frozenset({"complete", "input_required"})
    else:
        assert VERSION_FACTS[version].recognized_result_types == frozenset()
