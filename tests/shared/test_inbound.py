"""Pure-function tests of :mod:`mcp.shared.inbound`.

Independent verifier of the classifier: every ladder rung is exercised
pass+fail with no `mcp.server` / transport imports and no inlined error-code
or protocol-version literals — all facts are imported from their one source.
"""

import dataclasses
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
    find_invalid_x_mcp_header,
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
    "body",
    [
        pytest.param({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, id="no-params"),
        pytest.param({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, id="no-meta"),
        pytest.param(envelope(drop=frozenset({PROTOCOL_VERSION_META_KEY})), id="meta-missing-version"),
        pytest.param(envelope(drop=frozenset({CLIENT_INFO_META_KEY})), id="meta-missing-client-info"),
        pytest.param(envelope(drop=frozenset({CLIENT_CAPABILITIES_META_KEY})), id="meta-missing-client-caps"),
    ],
)
def test_envelope_rung_rejects_missing_keys(body: dict[str, Any]) -> None:
    """Spec-mandated: a modern request lacking any of the three reserved `_meta` keys is rejected INVALID_PARAMS."""
    rejection = assert_rejected(classify_inbound_request(body), INVALID_PARAMS)
    assert rejection.data is None


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
        pytest.param(_schema(a={"type": "object", "x-mcp-header": "Data"}), id="on-object"),
        pytest.param(_schema(a={"type": "array", "x-mcp-header": "Items"}), id="on-array"),
        pytest.param(_schema(a={"type": "null", "x-mcp-header": "Nil"}), id="on-null"),
        pytest.param(_schema(a={"type": "number", "x-mcp-header": "Ratio"}), id="on-number"),
        pytest.param(_schema(a={"type": ["string", "null"], "x-mcp-header": "Maybe"}), id="array-type"),
        pytest.param(_schema(a={"type": {"not": "valid"}, "x-mcp-header": "Bad"}), id="dict-type"),
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
            _schema(a={"type": "array", "items": {"type": "string", "x-mcp-header": "X"}}),
            id="under-items",
        ),
        pytest.param(
            {"allOf": [{"properties": {"a": {"type": "string", "x-mcp-header": "X"}}}]},
            id="under-allOf",
        ),
        pytest.param(
            {"oneOf": [{"type": "string", "x-mcp-header": "X"}]},
            id="under-oneOf",
        ),
        pytest.param(
            _schema(a={"if": {"type": "string", "x-mcp-header": "X"}}),
            id="under-if",
        ),
        pytest.param(
            {"$defs": {"T": {"type": "string", "x-mcp-header": "X"}}, "properties": {}},
            id="under-defs",
        ),
        pytest.param(
            {"patternProperties": {"^a": {"type": "string", "x-mcp-header": "X"}}},
            id="under-patternProperties",
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


def test_find_invalid_x_mcp_header_reports_dotted_path_for_nested_property() -> None:
    """SDK-defined: the reason string names the nested property by its dotted `properties` path."""
    schema = _schema(outer={"type": "object", "properties": {"r": {"type": "object", "x-mcp-header": "R"}}})
    reason = find_invalid_x_mcp_header(schema)
    assert reason is not None and "'outer.r'" in reason
