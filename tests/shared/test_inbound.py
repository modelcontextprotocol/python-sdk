"""Pure-function tests of :mod:`mcp.shared.inbound`.

Independent verifier of the classifier: every ladder rung is exercised
pass+fail with no `mcp.server` / transport imports and no inlined error-code
or protocol-version literals — all facts are imported from their one source.
"""

import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from mcp_types.jsonrpc import (
    HEADER_MISMATCH,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS

from mcp.shared.inbound import (
    _SUBSCHEMA_LIST,
    _SUBSCHEMA_MAP,
    _SUBSCHEMA_SINGLE,
    ERROR_CODE_HTTP_STATUS,
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
    NAME_BEARING_METHODS,
    InboundLadderRejection,
    InboundModernRoute,
    classify_inbound_request,
    decode_header_value,
    encode_header_value,
    find_duplicated_routing_header,
    find_invalid_x_mcp_header,
    mcp_param_headers,
    validate_mcp_param_headers,
    x_mcp_header_map,
)

CLIENT_INFO = {"name": "t", "version": "0"}
CLIENT_CAPS: dict[str, Any] = {}


def envelope(
    method: str = "tools/list",
    *,
    version: str = LATEST_MODERN_VERSION,
    drop: frozenset[str] = frozenset(),
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC body carrying a complete modern `_meta` envelope.

    `drop` removes named envelope keys so rung-1 failures are driven from one
    table instead of repeating reserved-key constants per call site.
    """
    meta: dict[str, Any] = {
        PROTOCOL_VERSION_META_KEY: version,
        CLIENT_INFO_META_KEY: CLIENT_INFO,
        CLIENT_CAPABILITIES_META_KEY: CLIENT_CAPS,
    }
    for key in drop:
        del meta[key]
    params: dict[str, Any] = {"_meta": meta}
    if extra_params:
        params.update(extra_params)
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def matching_headers(body: dict[str, Any]) -> dict[str, str]:
    """The minimal lowercase HTTP header set that agrees with `body` for rung 2."""
    headers = {
        MCP_PROTOCOL_VERSION_HEADER: body["params"]["_meta"][PROTOCOL_VERSION_META_KEY],
        MCP_METHOD_HEADER: body["method"],
    }
    name_key = NAME_BEARING_METHODS.get(body["method"])
    if name_key is not None and name_key in body["params"]:
        headers[MCP_NAME_HEADER] = encode_header_value(body["params"][name_key])
    return headers


def assert_rejected(result: object, code: int) -> InboundLadderRejection:
    assert isinstance(result, InboundLadderRejection)
    assert result.code == code
    return result


# --- rung 1: envelope-three-keys -----------------------------------------------


@pytest.mark.parametrize(
    ("body", "named"),
    [
        pytest.param(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            [PROTOCOL_VERSION_META_KEY, CLIENT_CAPABILITIES_META_KEY],
            id="no-params",
        ),
        pytest.param(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            [PROTOCOL_VERSION_META_KEY, CLIENT_CAPABILITIES_META_KEY],
            id="no-meta",
        ),
        pytest.param(
            envelope(drop=frozenset({PROTOCOL_VERSION_META_KEY})),
            [PROTOCOL_VERSION_META_KEY],
            id="meta-missing-version",
        ),
        pytest.param(
            envelope(drop=frozenset({CLIENT_CAPABILITIES_META_KEY})),
            [CLIENT_CAPABILITIES_META_KEY],
            id="meta-missing-client-caps",
        ),
        pytest.param(
            envelope(drop=frozenset({PROTOCOL_VERSION_META_KEY, CLIENT_CAPABILITIES_META_KEY})),
            [PROTOCOL_VERSION_META_KEY, CLIENT_CAPABILITIES_META_KEY],
            id="meta-missing-both",
        ),
    ],
)
def test_envelope_rung_rejects_missing_required_keys(body: dict[str, Any], named: list[str]) -> None:
    """Spec-mandated (basic/index.mdx per-request protocol fields): a modern
    request lacking a required `_meta` envelope key (protocol version or
    client capabilities) is rejected INVALID_PARAMS with a message naming the
    missing key(s)."""
    rejection = assert_rejected(classify_inbound_request(body), INVALID_PARAMS)
    assert rejection.data is None
    for key in named:
        assert key in rejection.message


def test_envelope_rung_accepts_pair_only_envelope_without_client_info() -> None:
    """Spec-mandated (spec PR #3002): `clientInfo` is optional - a request whose
    `_meta` carries only the protocol-version + client-capabilities pair
    routes, with `client_info` read as `None`."""
    result = classify_inbound_request(envelope(drop=frozenset({CLIENT_INFO_META_KEY})))
    assert isinstance(result, InboundModernRoute)
    assert result.protocol_version == LATEST_MODERN_VERSION
    assert result.client_info is None
    assert result.client_capabilities == CLIENT_CAPS


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": None}, id="params-none"),
        pytest.param({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": None}}, id="meta-none"),
        pytest.param(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": 0}}, id="meta-non-mapping"
        ),
    ],
)
def test_envelope_rung_rejects_non_mapping_shapes(body: dict[str, Any]) -> None:
    """Spec-mandated: non-mapping `params` / `_meta` cannot carry the envelope and reject INVALID_PARAMS."""
    assert_rejected(classify_inbound_request(body), INVALID_PARAMS)


@pytest.mark.parametrize("version", [7, None, ["2026-07-28"]], ids=["int", "null", "list"])
def test_envelope_rung_rejects_non_string_protocol_version(version: Any) -> None:
    """A present-but-non-string protocol version is a shape defect, rejected
    INVALID_PARAMS: it must never become -32022 (the one code auto-negotiating
    clients do not fall back from), and must not escape as a ValidationError
    from the version rung's own typed payload (`requested` is a `str` field)."""
    body = envelope()
    body["params"]["_meta"][PROTOCOL_VERSION_META_KEY] = version
    rejection = assert_rejected(classify_inbound_request(body), INVALID_PARAMS)
    assert "string" in rejection.message


def test_non_string_protocol_version_over_http_still_rejects_at_the_header_rung() -> None:
    """SDK-defined: the non-string guard sits after the header rung, so over
    HTTP a present version header (a string, which can never equal a
    non-string body value) keeps producing HEADER_MISMATCH - the guard's wire
    delta is confined to header-less transports."""
    body = envelope()
    headers = matching_headers(body)
    body["params"]["_meta"][PROTOCOL_VERSION_META_KEY] = 7
    assert_rejected(classify_inbound_request(body, headers=headers), HEADER_MISMATCH)


@pytest.mark.parametrize("version", [7, None], ids=["int", "null"])
def test_absent_version_header_rejects_before_the_string_guard(version: Any) -> None:
    """SDK-defined: the version header must be PRESENT, not merely equal - a
    null body version would otherwise slip the equality check (None == None)
    - so an absent header is HEADER_MISMATCH for every body value and the
    string guard stays reachable only on header-less transports."""
    body = envelope()
    headers = matching_headers(body)
    del headers[MCP_PROTOCOL_VERSION_HEADER]
    body["params"]["_meta"][PROTOCOL_VERSION_META_KEY] = version
    assert_rejected(classify_inbound_request(body, headers=headers), HEADER_MISMATCH)


# --- rung 2: protocol-version-supported ----------------------------------------


def test_version_rung_rejects_unsupported_with_data_shape() -> None:
    """Spec-mandated: an envelope version outside the modern set rejects with the `supported`/`requested` data."""
    rejection = assert_rejected(
        classify_inbound_request(envelope(version=LATEST_HANDSHAKE_VERSION)),
        UNSUPPORTED_PROTOCOL_VERSION,
    )
    assert rejection.data == {
        "supported": list(MODERN_PROTOCOL_VERSIONS),
        "requested": LATEST_HANDSHAKE_VERSION,
    }


def test_version_rung_data_reflects_supplied_supported_list() -> None:
    """SDK-defined: the caller-supplied `supported_modern_versions` is what rejection `data.supported` echoes."""
    custom = (LATEST_HANDSHAKE_VERSION,)
    rejection = assert_rejected(
        classify_inbound_request(envelope(), supported_modern_versions=custom),
        UNSUPPORTED_PROTOCOL_VERSION,
    )
    assert rejection.data == {"supported": list(custom), "requested": LATEST_MODERN_VERSION}


# --- rung 3: header ↔ envelope agreement ---------------------------------------


def test_header_rung_does_not_reject_when_headers_arg_is_none() -> None:
    """SDK-defined: `headers=None` (non-HTTP transports) means rung 3 has nothing to check and the ladder proceeds."""
    result = classify_inbound_request(envelope(), headers=None)
    assert isinstance(result, InboundModernRoute)


def test_header_rung_passes_when_header_matches_envelope() -> None:
    """Spec-mandated: an HTTP version header equal to the envelope version passes rung 3."""
    body = envelope()
    result = classify_inbound_request(body, headers=matching_headers(body))
    assert isinstance(result, InboundModernRoute)


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({MCP_PROTOCOL_VERSION_HEADER: LATEST_HANDSHAKE_VERSION}, id="mismatch"),
        pytest.param({}, id="header-absent"),
    ],
)
def test_header_rung_rejects_on_disagreement(headers: dict[str, str]) -> None:
    """Spec-mandated: an absent or mismatched HTTP version header rejects HEADER_MISMATCH."""
    assert_rejected(classify_inbound_request(envelope(), headers=headers), HEADER_MISMATCH)


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({MCP_METHOD_HEADER: "prompts/list"}, id="method-mismatch"),
        pytest.param({MCP_METHOD_HEADER: "TOOLS/LIST"}, id="method-case-mismatch"),
    ],
)
def test_header_rung_rejects_method_header_disagreement(override: dict[str, str]) -> None:
    """Spec-mandated: `Mcp-Method` must equal `body.method` exactly (case-sensitive) → else HEADER_MISMATCH."""
    body = envelope()
    rejection = assert_rejected(
        classify_inbound_request(body, headers=matching_headers(body) | override), HEADER_MISMATCH
    )
    assert MCP_METHOD_HEADER in rejection.message


def test_header_rung_rejects_missing_method_header() -> None:
    """Spec-mandated: an HTTP request on the modern path without `Mcp-Method` is HEADER_MISMATCH."""
    body = envelope()
    headers = matching_headers(body)
    del headers[MCP_METHOD_HEADER]
    assert_rejected(classify_inbound_request(body, headers=headers), HEADER_MISMATCH)


@pytest.mark.parametrize(
    ("method", "name_key"),
    [(m, k) for m, k in NAME_BEARING_METHODS.items()],
)
def test_header_rung_rejects_missing_or_mismatched_name_header_for_name_bearing_methods(
    method: str, name_key: str
) -> None:
    """Spec-mandated: when the body carries the named param, `Mcp-Name` must be present and equal it."""
    body = envelope(method, extra_params={name_key: "expected"})
    headers = matching_headers(body)
    # Mismatch
    assert_rejected(classify_inbound_request(body, headers=headers | {MCP_NAME_HEADER: "wrong"}), HEADER_MISMATCH)
    # Absent
    del headers[MCP_NAME_HEADER]
    assert_rejected(classify_inbound_request(body, headers=headers), HEADER_MISMATCH)


def test_header_rung_decodes_base64_sentinel_before_comparing_name() -> None:
    """Spec-mandated: servers MUST decode the `=?base64?...?=` sentinel before comparing `Mcp-Name`."""
    body = envelope("tools/call", extra_params={"name": "résumé"})
    headers = matching_headers(body)
    assert headers[MCP_NAME_HEADER].startswith("=?base64?")
    result = classify_inbound_request(body, headers=headers)
    assert isinstance(result, InboundModernRoute)


def test_header_rung_does_not_require_name_header_for_non_name_bearing_method() -> None:
    """SDK-defined: a method outside `NAME_BEARING_METHODS` ignores `Mcp-Name` entirely."""
    body = envelope("tools/list")
    result = classify_inbound_request(body, headers=matching_headers(body) | {MCP_NAME_HEADER: "anything"})
    assert isinstance(result, InboundModernRoute)


def test_header_rung_does_not_require_name_header_when_body_omits_the_named_param() -> None:
    """SDK-defined: a name-bearing method whose body lacks the named param skips the `Mcp-Name`
    check — the param's absence is INVALID_PARAMS later, not HEADER_MISMATCH here."""
    body = envelope("tools/call")
    result = classify_inbound_request(body, headers=matching_headers(body))
    assert isinstance(result, InboundModernRoute)


# --- all rungs pass ------------------------------------------------------------


def test_all_rungs_pass_yields_route() -> None:
    """Spec-mandated: a complete envelope at a supported version with agreeing header routes, surfacing the envelope."""
    body = envelope()
    result = classify_inbound_request(body, headers=matching_headers(body))
    assert isinstance(result, InboundModernRoute)
    assert result.protocol_version == LATEST_MODERN_VERSION
    assert result.client_info == CLIENT_INFO
    assert result.client_capabilities == CLIENT_CAPS


@pytest.mark.parametrize("method", ["initialize", "myorg/custom", "does/not/exist"])
def test_classifier_passes_unknown_method_through_to_route(method: str) -> None:
    """SDK-defined: the classifier does not gate on method — kernel dispatch is the single owner of that decision."""
    body = envelope(method)
    result = classify_inbound_request(body, headers=matching_headers(body))
    assert isinstance(result, InboundModernRoute)


def test_ladder_first_failure_wins() -> None:
    """Spec-mandated: rungs evaluate in order — header-mismatch and version-unsupported
    would both fail; the header rung fires first so an inconsistent client is told it
    disagrees with itself rather than that its body version is unsupported."""
    body = envelope(version=LATEST_HANDSHAKE_VERSION)
    result = classify_inbound_request(body, headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION})
    assert_rejected(result, HEADER_MISMATCH)


# --- ERROR_CODE_HTTP_STATUS ----------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (PARSE_ERROR, 400),
        (INVALID_REQUEST, 400),
        (INVALID_PARAMS, 400),
        (HEADER_MISMATCH, 400),
        (MISSING_REQUIRED_CLIENT_CAPABILITY, 400),
        (UNSUPPORTED_PROTOCOL_VERSION, 400),
        (METHOD_NOT_FOUND, 404),
    ],
)
def test_error_code_http_status_table(code: int, status: int) -> None:
    """SDK-defined: pins the JSON-RPC error code → HTTP status mapping the streamable transport reads."""
    assert ERROR_CODE_HTTP_STATUS[code] == status


def test_error_code_http_status_covers_every_ladder_code() -> None:
    """SDK-defined: every code the ladder can emit has an HTTP-status entry, so the transport never has to default."""
    ladder_codes = {INVALID_PARAMS, UNSUPPORTED_PROTOCOL_VERSION, HEADER_MISMATCH}
    assert ladder_codes <= ERROR_CODE_HTTP_STATUS.keys()


# --- shape invariants ----------------------------------------------------------


def test_verdict_dataclasses_are_frozen() -> None:
    """SDK-defined: both verdict dataclasses are frozen so a route/rejection cannot be mutated after classification."""
    route = classify_inbound_request(envelope())
    assert isinstance(route, InboundModernRoute)
    rejection = InboundLadderRejection(code=METHOD_NOT_FOUND, message="m")
    for verdict in (route, rejection):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(verdict, "message", "mutated")


# --- header-value codec --------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["plain", "with internal space", "", " edge-ws ", "résumé", "a\r\nb", "=?base64?Zm9v?="],
)
def test_decode_header_value_round_trips_encode(raw: str) -> None:
    """SDK-defined: `decode_header_value` is the exact inverse of `encode_header_value` over the full input domain."""
    assert decode_header_value(encode_header_value(raw)) == raw


def test_decode_header_value_passes_none_and_plain_through() -> None:
    """SDK-defined: `None` in → `None` out so callers can pass `headers.get(...)` directly; plain stays verbatim."""
    assert decode_header_value(None) is None
    assert decode_header_value("plain") == "plain"


@pytest.mark.parametrize("bad", ["=?base64?not base64!?=", "=?base64?gA==?="])
def test_decode_header_value_returns_none_for_malformed_sentinel(bad: str) -> None:
    """SDK-defined: a sentinel with bad base64 or bad UTF-8 decodes to `None`, so it can never match a body value."""
    assert decode_header_value(bad) is None


# --- NAME_BEARING_METHODS ------------------------------------------------------


def test_name_bearing_methods_table_matches_spec() -> None:
    """Spec-mandated: pins the method → name-param table the client emit and server validate share."""
    assert NAME_BEARING_METHODS == {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}


# --- find_invalid_x_mcp_header -------------------------------------------------


def _schema(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props}


@pytest.mark.parametrize(
    "input_schema",
    [
        pytest.param(None, id="none"),
        pytest.param("not-a-mapping", id="non-mapping"),
        pytest.param({"type": "object"}, id="no-properties"),
        pytest.param({"type": "object", "properties": "not-a-mapping"}, id="properties-non-mapping"),
        pytest.param(_schema(a={"type": "string"}), id="no-annotation"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": "Region"}), id="valid-string"),
        pytest.param(_schema(a={"type": "integer", "x-mcp-header": "Count"}), id="valid-integer"),
        pytest.param(_schema(a={"type": "boolean", "x-mcp-header": "Flag"}), id="valid-boolean"),
        pytest.param(
            _schema(a={"type": "string", "x-mcp-header": "A"}, b={"type": "string", "x-mcp-header": "B"}),
            id="two-distinct",
        ),
        pytest.param(_schema(a="not-a-mapping", b={"type": "string", "x-mcp-header": "B"}), id="non-mapping-prop"),
        pytest.param(
            _schema(outer={"type": "object", "properties": {"r": {"type": "string", "x-mcp-header": "R"}}}),
            id="nested-on-properties-chain",
        ),
        pytest.param(
            _schema(a={"type": "string", "default": {"x-mcp-header": "ignored"}}),
            id="annotation-lookalike-in-default-is-data",
        ),
        pytest.param(
            _schema(a={"type": "string", "examples": [{"x-mcp-header": "ignored"}]}),
            id="annotation-lookalike-in-examples-is-data",
        ),
        pytest.param(
            _schema(a={"type": "string", "const": {"x-mcp-header": "ignored"}}),
            id="annotation-lookalike-in-const-is-data",
        ),
        pytest.param(
            _schema(a={"type": "string", "enum": [{"x-mcp-header": "ignored"}]}),
            id="annotation-lookalike-in-enum-is-data",
        ),
        pytest.param(
            {"properties": {"a": {"type": "string", "x-mcp-header": "R"}}, "$ref": "#/$defs/loop"},
            id="ref-is-not-dereferenced",
        ),
        pytest.param(
            {"type": "object", "allOf": 0, "anyOf": [], "$defs": 0, "patternProperties": {}},
            id="malformed-or-empty-applicators-ignored",
        ),
    ],
)
def test_find_invalid_x_mcp_header_accepts_valid_or_absent_annotations(input_schema: Any) -> None:
    """Spec-mandated: a schema without annotations, or with annotations that are RFC 9110 tokens on
    integer/string/boolean properties reachable via a pure `properties` chain and case-insensitively
    unique across the whole schema, is valid."""
    assert find_invalid_x_mcp_header(input_schema) is None


@pytest.mark.parametrize(
    "input_schema",
    [
        pytest.param(_schema(a={"type": "string", "x-mcp-header": ""}), id="empty"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": "My Region"}), id="space"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": "Region:Primary"}), id="colon"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": "Région"}), id="non-ascii"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": "Region\t1"}), id="control-char"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": 42}), id="non-string"),
        pytest.param(_schema(a={"type": "string", "x-mcp-header": 10**5000}), id="oversized-int-header"),
        pytest.param(_schema(a={"type": "object", "x-mcp-header": "Data"}), id="on-object"),
        pytest.param(_schema(a={"type": "array", "x-mcp-header": "Items"}), id="on-array"),
        pytest.param(_schema(a={"type": "null", "x-mcp-header": "Nil"}), id="on-null"),
        pytest.param(_schema(a={"type": "number", "x-mcp-header": "Ratio"}), id="on-number"),
        pytest.param(_schema(a={"type": ["string", "null"], "x-mcp-header": "Maybe"}), id="array-type"),
        pytest.param(_schema(a={"type": {"not": "valid"}, "x-mcp-header": "Bad"}), id="dict-type"),
        pytest.param(_schema(a={"type": 10**5000, "x-mcp-header": "Big"}), id="oversized-int-type"),
        pytest.param(_schema(a={"x-mcp-header": "NoType"}), id="missing-type"),
        pytest.param(
            _schema(a={"type": "string", "x-mcp-header": "Region"}, b={"type": "string", "x-mcp-header": "Region"}),
            id="duplicate-same-case",
        ),
        pytest.param(
            _schema(a={"type": "string", "x-mcp-header": "MyField"}, b={"type": "string", "x-mcp-header": "myfield"}),
            id="duplicate-diff-case",
        ),
        pytest.param(
            {"allOf": [{"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "X"}}}]},
            id="properties-chain-not-restored-below-an-applicator",
        ),
        pytest.param(
            {"type": "string", "x-mcp-header": "X"},
            id="on-root-schema",
        ),
        pytest.param(
            _schema(
                a={"type": "string", "x-mcp-header": "Region"},
                o={"type": "object", "properties": {"b": {"type": "string", "x-mcp-header": "region"}}},
            ),
            id="duplicate-across-nesting-levels",
        ),
        pytest.param(
            _schema(outer={"type": "object", "properties": {"r": {"type": "string", "x-mcp-header": "bad name"}}}),
            id="nested-bad-token",
        ),
        pytest.param(
            _schema(outer={"type": "object", "properties": {"r": {"type": "object", "x-mcp-header": "R"}}}),
            id="nested-non-primitive",
        ),
    ],
)
def test_find_invalid_x_mcp_header_rejects_malformed_annotations(input_schema: dict[str, Any]) -> None:
    """Spec-mandated: empty / non-token / non-primitive / off-chain / duplicate `x-mcp-header`
    annotations yield a reason string."""
    assert isinstance(find_invalid_x_mcp_header(input_schema), str)


# Keyword → a value of that keyword's own JSON Schema shape carrying an annotated subschema.
# Deliberately a literal table, independent of the `_SUBSCHEMA_*` sets in `inbound.py`:
# dropping a keyword from the walk must FAIL its case here, not shrink the parametrization.
_ANNOTATED = {"type": "string", "x-mcp-header": "Region"}
_APPLICATOR_CASES: dict[str, Any] = {
    "$defs": {"T": _ANNOTATED},
    "additionalProperties": _ANNOTATED,
    "allOf": [_ANNOTATED],
    "anyOf": [_ANNOTATED],
    "contains": _ANNOTATED,
    "contentSchema": _ANNOTATED,
    "definitions": {"T": _ANNOTATED},
    "dependentSchemas": {"k": _ANNOTATED},
    "else": _ANNOTATED,
    "if": _ANNOTATED,
    "items": _ANNOTATED,
    "not": _ANNOTATED,
    "oneOf": [_ANNOTATED],
    "patternProperties": {"^a": _ANNOTATED},
    "prefixItems": [_ANNOTATED],
    "propertyNames": _ANNOTATED,
    "then": _ANNOTATED,
    "unevaluatedItems": _ANNOTATED,
    "unevaluatedProperties": _ANNOTATED,
}


@pytest.mark.parametrize("keyword", sorted(_APPLICATOR_CASES))
def test_find_invalid_x_mcp_header_rejects_annotations_under_every_non_properties_applicator(keyword: str) -> None:
    """Spec-mandated: a property reached through any applicator other than `properties` is not
    statically reachable, so its annotation invalidates the whole tool definition."""
    schema = _schema(ok={"type": "string"}) | {keyword: _APPLICATOR_CASES[keyword]}
    assert isinstance(find_invalid_x_mcp_header(schema), str)


def test_schema_walk_applicator_keywords_match_the_pinned_reject_cases() -> None:
    """SDK-defined: a keyword added to the walk must gain a literal reject case above (a removed
    keyword already fails its case there)."""
    assert _SUBSCHEMA_LIST | _SUBSCHEMA_MAP | _SUBSCHEMA_SINGLE == set(_APPLICATOR_CASES)


def test_find_invalid_x_mcp_header_reports_dotted_path_for_nested_property() -> None:
    """SDK-defined: the reason string names the nested property by its dotted `properties` path."""
    schema = _schema(outer={"type": "object", "properties": {"r": {"type": "object", "x-mcp-header": "R"}}})
    reason = find_invalid_x_mcp_header(schema)
    assert reason is not None and "'outer.r'" in reason


# --- x_mcp_header_map ----------------------------------------------------------


def test_x_mcp_header_map_keys_top_level_and_nested_properties_by_path() -> None:
    """Each annotated property maps to its token under its full `properties` path; unannotated props are absent."""
    schema = _schema(
        region={"type": "string", "x-mcp-header": "Region"},
        query={"type": "string"},
        outer={"type": "object", "properties": {"inner": {"type": "string", "x-mcp-header": "Inner"}}},
    )
    assert x_mcp_header_map(schema) == {("region",): "Region", ("outer", "inner"): "Inner"}


@pytest.mark.parametrize("input_schema", [None, "not-a-mapping", {"type": "object"}])
def test_x_mcp_header_map_empty_for_schemas_without_annotations(input_schema: Any) -> None:
    assert x_mcp_header_map(input_schema) == {}


# --- mcp_param_headers ---------------------------------------------------------


def test_mcp_param_headers_renders_primitive_types_per_spec() -> None:
    """String verbatim, integer as decimal, boolean as lowercase `true`/`false`, header named `Mcp-Param-<token>`."""
    header_map = {("region",): "Region", ("priority",): "Priority", ("verbose",): "Verbose", ("debug",): "Debug"}
    arguments = {"region": "us-west1", "priority": 42, "verbose": False, "debug": True}
    assert mcp_param_headers(header_map, arguments) == {
        "Mcp-Param-Region": "us-west1",
        "Mcp-Param-Priority": "42",
        "Mcp-Param-Verbose": "false",
        "Mcp-Param-Debug": "true",
    }


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        pytest.param("us-west1", "us-west1", id="plain-ascii"),
        pytest.param("Hello, 世界", "=?base64?SGVsbG8sIOS4lueVjA==?=", id="non-ascii"),
        pytest.param(" padded ", "=?base64?IHBhZGRlZCA=?=", id="edge-whitespace"),
        pytest.param("line1\nline2", "=?base64?bGluZTEKbGluZTI=?=", id="control-char"),
        pytest.param("=?base64?literal?=", "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=", id="sentinel-lookalike"),
    ],
)
def test_mcp_param_headers_base64_wraps_header_unsafe_strings(value: str, encoded: str) -> None:
    """Matches the spec's Value Encoding table: a non-header-safe string is base64-sentinel wrapped."""
    assert mcp_param_headers({("v",): "Val"}, {"v": value}) == {"Mcp-Param-Val": encoded}


def test_mcp_param_headers_omits_absent_or_null_arguments() -> None:
    """A path that hits a missing key or a `None` value emits no header (spec: omit when no value is present)."""
    header_map = {("present",): "Present", ("missing",): "Missing", ("nulled",): "Nulled"}
    assert mcp_param_headers(header_map, {"present": "x", "nulled": None}) == {"Mcp-Param-Present": "x"}


def test_mcp_param_headers_reads_nested_argument_path() -> None:
    """A nested annotated property reads its value at the matching nested `arguments` path."""
    headers = mcp_param_headers({("outer", "inner"): "Inner"}, {"outer": {"inner": "deep"}})
    assert headers == {"Mcp-Param-Inner": "deep"}


def test_mcp_param_headers_omits_when_nested_path_is_broken() -> None:
    """A nested path through a non-mapping or missing intermediate node yields no header."""
    header_map = {("outer", "inner"): "Inner"}
    assert mcp_param_headers(header_map, {"outer": "not-a-mapping"}) == {}
    assert mcp_param_headers(header_map, {}) == {}


# --- validate_mcp_param_headers --------------------------------------------

REGION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"region": {"type": "string", "x-mcp-header": "Region"}},
}


@pytest.mark.parametrize(
    ("argument", "header"),
    [
        pytest.param("Hello", "Hello", id="plain-literal"),
        pytest.param("Hello", "=?base64?SGVsbG8=?=", id="valid-sentinel"),
        pytest.param("", "=?base64??=", id="empty-sentinel"),
        pytest.param("SGVsbG8=", "SGVsbG8=", id="missing-prefix-is-literal"),
        pytest.param("=?base64?SGVsbG8=", "=?base64?SGVsbG8=", id="missing-suffix-is-literal"),
    ],
)
def test_validate_mcp_param_headers_accepts_agreeing_header_and_argument(argument: str, header: str) -> None:
    """Spec Value Encoding: a fully-wrapped sentinel decodes before comparison; anything else is a literal."""
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": argument}, {"Mcp-Param-Region": header}) is None


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("=?base64?SGVsbG8?=", id="missing-padding"),
        pytest.param("=?base64?SGVs!!!bG8=?=", id="non-alphabet-chars"),
        pytest.param("=?base64?SGVsbG9=?=", id="non-canonical-trailing-bits"),
        pytest.param("=?base64?gA==?=", id="invalid-utf8"),
    ],
)
def test_validate_mcp_param_headers_rejects_malformed_sentinel(header: str) -> None:
    """Spec: servers MUST reject a recognized header whose sentinel cannot be strictly decoded — not a literal."""
    rejection = assert_rejected(
        validate_mcp_param_headers(REGION_SCHEMA, {"region": "Hello"}, {"Mcp-Param-Region": header}),
        HEADER_MISMATCH,
    )
    assert "malformed base64" in rejection.message


def test_validate_mcp_param_headers_rejects_missing_header_for_present_argument() -> None:
    """Spec table: client omits the header but the value is in the body → server MUST reject."""
    rejection = assert_rejected(
        validate_mcp_param_headers(REGION_SCHEMA, {"region": "test-value"}, {}), HEADER_MISMATCH
    )
    assert "missing" in rejection.message


@pytest.mark.parametrize(
    "arguments",
    [pytest.param({}, id="absent"), pytest.param({"region": None}, id="null")],
)
def test_validate_mcp_param_headers_rejects_orphan_header_for_absent_or_null_argument(
    arguments: dict[str, Any],
) -> None:
    """SDK-defined posture on a spec gap: an orphan header is the routing-spoof case; go rejects too, ts skips."""
    rejection = assert_rejected(
        validate_mcp_param_headers(REGION_SCHEMA, arguments, {"Mcp-Param-Region": "eu"}), HEADER_MISMATCH
    )
    assert "absent" in rejection.message


def test_validate_mcp_param_headers_rejects_value_mismatch() -> None:
    rejection = assert_rejected(
        validate_mcp_param_headers(REGION_SCHEMA, {"region": "us"}, {"Mcp-Param-Region": "eu"}), HEADER_MISMATCH
    )
    assert "does not match" in rejection.message


def test_validate_mcp_param_headers_accepts_absent_argument_with_no_header() -> None:
    """Spec table: parameter not in arguments / null → client MUST omit, server MUST NOT expect."""
    assert validate_mcp_param_headers(REGION_SCHEMA, {}, {}) is None
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": None}, {}) is None


def test_validate_mcp_param_headers_matches_header_names_case_insensitively() -> None:
    """Spec Case Sensitivity: header-name comparison MUST be case-insensitive."""
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": "eu"}, {"MCP-PARAM-REGION": "eu"}) is None
    rejection = validate_mcp_param_headers(REGION_SCHEMA, {"region": "us"}, {"MCP-PARAM-REGION": "eu"})
    assert_rejected(rejection, HEADER_MISMATCH)


def test_validate_mcp_param_headers_ignores_undeclared_mcp_param_headers() -> None:
    """Spec: an undeclared `Mcp-Param-*` header is unrecognized — forwarded and ignored, never a failure."""
    headers = {"Mcp-Param-Region": "eu", "Mcp-Param-Undeclared": "=?base64?not even base64?="}
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": "eu"}, headers) is None


def test_validate_mcp_param_headers_validates_nothing_for_an_invalid_annotation_schema() -> None:
    """Spec gives definition rejection to clients (drop the tool), so an invalid schema recognizes no headers."""
    invalid = {
        "type": "object",
        "properties": {
            "region": {"type": "string", "x-mcp-header": "Region"},
            "dupe": {"type": "string", "x-mcp-header": "region"},
        },
    }
    assert find_invalid_x_mcp_header(invalid) is not None
    assert validate_mcp_param_headers(invalid, {"region": "us"}, {"Mcp-Param-Region": "eu"}) is None


def test_validate_mcp_param_headers_reads_nested_argument_paths() -> None:
    """A nested annotated property compares against the matching nested `arguments` path; a broken path is absent."""
    schema = {
        "type": "object",
        "properties": {
            "outer": {"type": "object", "properties": {"inner": {"type": "string", "x-mcp-header": "Inner"}}}
        },
    }
    assert validate_mcp_param_headers(schema, {"outer": {"inner": "deep"}}, {"Mcp-Param-Inner": "deep"}) is None
    rejection = validate_mcp_param_headers(schema, {"outer": {"inner": "deep"}}, {"Mcp-Param-Inner": "other"})
    assert_rejected(rejection, HEADER_MISMATCH)
    assert validate_mcp_param_headers(schema, {"outer": "not-a-mapping"}, {}) is None


def test_validate_mcp_param_headers_compares_booleans_against_true_false_rendering() -> None:
    """Booleans compare against the lowercase `true`/`false` rendering the client emits."""
    schema = {"type": "object", "properties": {"flag": {"type": "boolean", "x-mcp-header": "Flag"}}}
    assert validate_mcp_param_headers(schema, {"flag": True}, {"Mcp-Param-Flag": "true"}) is None
    assert validate_mcp_param_headers(schema, {"flag": False}, {"Mcp-Param-Flag": "false"}) is None
    rejection = validate_mcp_param_headers(schema, {"flag": True}, {"Mcp-Param-Flag": "True"})
    assert_rejected(rejection, HEADER_MISMATCH)


INTEGER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"n": {"type": "integer", "x-mcp-header": "N"}},
}


@pytest.mark.parametrize(
    ("body_value", "header", "matches"),
    [
        pytest.param(42, "42", True, id="exact"),
        pytest.param(42, "42.0", True, id="trailing-zero-fraction"),
        pytest.param(42, "42.000", True, id="long-zero-fraction"),
        pytest.param(42, "42.5", False, id="real-fraction"),
        pytest.param(42, "1e2", False, id="scientific-notation-never-numeric"),
        pytest.param(42, "43", False, id="different-value"),
        pytest.param(-7, "-7.0", True, id="negative"),
        pytest.param(9007199254740993, "9007199254740993", True, id="beyond-ieee754-safe-range-exact"),
        pytest.param(9007199254740993, "9007199254740992", False, id="beyond-ieee754-safe-range-off-by-one"),
    ],
)
def test_validate_mcp_param_headers_compares_integers_numerically(body_value: int, header: str, matches: bool) -> None:
    """Spec SHOULD: integers compare numerically (`42` == `42.0`) — gated to canonical decimals, compared exactly."""
    result = validate_mcp_param_headers(INTEGER_SCHEMA, {"n": body_value}, {"Mcp-Param-N": header})
    if matches:
        assert result is None
    else:
        assert_rejected(result, HEADER_MISMATCH)


def test_validate_mcp_param_headers_non_primitive_body_value_rejects_only_when_a_header_claims_it() -> None:
    """A header claiming a non-primitive argument is a mismatch; without one, rejection is params validation's job."""
    rejection = assert_rejected(
        validate_mcp_param_headers(REGION_SCHEMA, {"region": {"k": "v"}}, {"Mcp-Param-Region": "x"}),
        HEADER_MISMATCH,
    )
    assert "does not match" in rejection.message
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": {"k": "v"}}, {}) is None
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": [1, 2]}, {}) is None


class _RepeatedHeaders(Mapping[str, str]):
    """A header carrier whose `items()` yields duplicate names, like a raw HTTP header list."""

    def __init__(self, pairs: list[tuple[str, str]]) -> None:
        self._pairs = pairs

    def __getitem__(self, key: str) -> str:
        return next(value for name, value in self._pairs if name == key)

    def __iter__(self) -> Iterator[str]:
        return (name for name, _ in self._pairs)

    def __len__(self) -> int:
        return len(self._pairs)

    def items(self) -> Any:
        return list(self._pairs)


def test_validate_mcp_param_headers_rejects_a_recognized_header_supplied_more_than_once() -> None:
    """Duplicate recognized headers reject even when one matches: first-copy readers and last-wins checks diverge."""
    headers = _RepeatedHeaders([("Mcp-Param-Region", "spoofed"), ("mcp-param-region", "eu")])
    # The carrier behaves like a raw header list: first-wins lookup, every line iterated.
    assert headers["Mcp-Param-Region"] == "spoofed"
    assert len(headers) == len(list(headers)) == 2
    rejection = assert_rejected(validate_mcp_param_headers(REGION_SCHEMA, {"region": "eu"}, headers), HEADER_MISMATCH)
    assert "more than once" in rejection.message
    noisy = _RepeatedHeaders([("Mcp-Param-Region", "eu"), ("Mcp-Param-Other", "a"), ("mcp-param-other", "b")])
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": "eu"}, noisy) is None


def test_validate_mcp_param_headers_rejects_a_header_exceeding_the_int_conversion_limit() -> None:
    """A canonical-decimal header beyond CPython's int-conversion digit limit is a clean mismatch, never an error."""
    rejection = validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 1}, {"Mcp-Param-N": "1" * 5000})
    assert_rejected(rejection, HEADER_MISMATCH)


def test_validate_mcp_param_headers_compares_integral_float_bodies_numerically() -> None:
    """JSON Schema admits `42.0` as an integer; the numeric SHOULD applies in both directions."""
    assert validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 42.0}, {"Mcp-Param-N": "42"}) is None
    assert validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 42.0}, {"Mcp-Param-N": "42.0"}) is None
    assert_rejected(validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 42.0}, {"Mcp-Param-N": "43"}), HEADER_MISMATCH)
    # A genuinely fractional body value falls back to the exact string rendering.
    assert validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 42.5}, {"Mcp-Param-N": "42.5"}) is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("=?base64?SGVsbG9=?=", id="non-canonical-trailing-bits"),
        pytest.param("=?base64?SGVsbG8?=", id="missing-padding"),
    ],
)
def test_decode_header_value_returns_none_for_non_canonical_base64(value: str) -> None:
    """Canonical base64 only: a payload that decodes but does not re-encode byte-identically is malformed."""
    assert decode_header_value(value) is None


def test_validate_mcp_param_headers_union_typed_annotation_invalidates_the_whole_tool() -> None:
    """A union-typed annotation fails the integer/string/boolean-only rule, so the whole schema validates nothing."""
    union_schema = {
        "type": "object",
        "properties": {"n": {"type": ["integer", "null"], "x-mcp-header": "N"}},
    }
    assert find_invalid_x_mcp_header(union_schema) is not None
    assert validate_mcp_param_headers(union_schema, {"n": 42}, {"Mcp-Param-N": "999"}) is None
    assert validate_mcp_param_headers(union_schema, {"n": 42}, {}) is None


def test_validate_mcp_param_headers_accepts_the_clients_own_rendering_of_large_integral_floats() -> None:
    """A non-canonical-decimal header falls back to rendered comparison, so the client's own mirroring round-trips."""
    emitted = mcp_param_headers(x_mcp_header_map(INTEGER_SCHEMA), {"n": 1e16})
    assert emitted == {"Mcp-Param-N": "1e+16"}
    assert validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 1e16}, emitted) is None
    assert_rejected(validate_mcp_param_headers(INTEGER_SCHEMA, {"n": 42}, {"Mcp-Param-N": "1e2"}), HEADER_MISMATCH)


def test_validate_mcp_param_headers_handles_unrenderable_huge_integer_bodies_without_raising() -> None:
    """An integer beyond CPython's int-to-str digit limit has no rendering: claimed → mismatch, unclaimed → fine."""
    huge = 10**5000
    rejection = validate_mcp_param_headers(REGION_SCHEMA, {"region": huge}, {"Mcp-Param-Region": "x"})
    assert_rejected(rejection, HEADER_MISMATCH)
    assert validate_mcp_param_headers(REGION_SCHEMA, {"region": huge}, {}) is None
    assert validate_mcp_param_headers(INTEGER_SCHEMA, {"n": huge}, {}) is None


def test_mcp_param_headers_omits_values_with_no_scalar_rendering() -> None:
    """Objects, arrays, and over-limit integers have no scalar rendering, so the client omits the header."""
    header_map = {("v",): "Val"}
    assert mcp_param_headers(header_map, {"v": {"k": 1}}) == {}
    assert mcp_param_headers(header_map, {"v": [1, 2]}) == {}
    assert mcp_param_headers(header_map, {"v": 10**5000}) == {}


def test_find_duplicated_routing_header_detects_repeats_of_routing_headers_only() -> None:
    """Repeated routing headers report case-insensitively; `Mcp-Param-*` or unrelated repeats are ignored."""
    assert find_duplicated_routing_header([("Mcp-Name", "a"), ("mcp-name", "b")]) == MCP_NAME_HEADER
    assert find_duplicated_routing_header([("MCP-Protocol-Version", "x"), ("mcp-protocol-version", "x")]) == (
        MCP_PROTOCOL_VERSION_HEADER
    )
    assert find_duplicated_routing_header([("Mcp-Method", "a"), ("Mcp-Method", "a")]) == MCP_METHOD_HEADER
    assert find_duplicated_routing_header([("Mcp-Name", "a"), ("Mcp-Param-X", "1"), ("Mcp-Param-X", "2")]) is None
    assert find_duplicated_routing_header([("accept", "a"), ("accept", "b")]) is None
