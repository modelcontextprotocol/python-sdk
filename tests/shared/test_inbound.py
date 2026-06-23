"""Pure-function tests of :mod:`mcp.shared.inbound`.

Independent verifier of the classifier: every ladder rung is exercised
pass+fail with no ``mcp.server`` / transport imports and no inlined error-code
or protocol-version literals — all facts are imported from their one source.
"""

import dataclasses
from typing import Any

import pytest

from mcp.shared.inbound import (
    ERROR_CODE_HTTP_STATUS,
    MCP_PROTOCOL_VERSION_HEADER,
    InboundLadderRejection,
    InboundModernRoute,
    classify_inbound_request,
)
from mcp.shared.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS
from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from mcp.types.jsonrpc import (
    HEADER_MISMATCH,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
)

MODERN = LATEST_MODERN_VERSION
"""The modern protocol-version string, read from the registry — never inlined here."""

CLIENT_INFO = {"name": "t", "version": "0"}
CLIENT_CAPS: dict[str, Any] = {}


def envelope(
    method: str = "tools/list",
    *,
    version: str = MODERN,
    drop: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Build a JSON-RPC body carrying a complete modern ``_meta`` envelope.

    ``drop`` removes named envelope keys so rung-1 failures are driven from one
    table instead of repeating reserved-key constants per call site.
    """
    meta: dict[str, Any] = {
        PROTOCOL_VERSION_META_KEY: version,
        CLIENT_INFO_META_KEY: CLIENT_INFO,
        CLIENT_CAPABILITIES_META_KEY: CLIENT_CAPS,
    }
    for key in drop:
        del meta[key]
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": {"_meta": meta}}


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
    """Spec-mandated: a modern request lacking any of the three reserved ``_meta`` keys is rejected INVALID_PARAMS."""
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
    """Spec-mandated: non-mapping ``params`` / ``_meta`` cannot carry the envelope and reject INVALID_PARAMS."""
    assert_rejected(classify_inbound_request(body), INVALID_PARAMS)


# --- rung 2: protocol-version-supported ----------------------------------------


def test_version_rung_rejects_unsupported_with_data_shape() -> None:
    """Spec-mandated: an envelope version outside the modern set rejects with the ``supported``/``requested`` data."""
    rejection = assert_rejected(
        classify_inbound_request(envelope(version=LATEST_HANDSHAKE_VERSION)),
        UNSUPPORTED_PROTOCOL_VERSION,
    )
    assert rejection.data == {
        "supported": list(MODERN_PROTOCOL_VERSIONS),
        "requested": LATEST_HANDSHAKE_VERSION,
    }


def test_version_rung_data_reflects_supplied_supported_list() -> None:
    """SDK-defined: the caller-supplied ``supported_modern_versions`` is what rejection ``data.supported`` echoes."""
    custom = (LATEST_HANDSHAKE_VERSION,)
    rejection = assert_rejected(
        classify_inbound_request(envelope(), supported_modern_versions=custom),
        UNSUPPORTED_PROTOCOL_VERSION,
    )
    assert rejection.data == {"supported": list(custom), "requested": MODERN}


# --- rung 3: header ↔ envelope agreement ---------------------------------------


def test_header_rung_does_not_reject_when_headers_arg_is_none() -> None:
    """SDK-defined: ``headers=None`` (non-HTTP transports) means rung 3 has nothing to check and the ladder proceeds."""
    result = classify_inbound_request(envelope(), headers=None)
    assert isinstance(result, InboundModernRoute)


def test_header_rung_passes_when_header_matches_envelope() -> None:
    """Spec-mandated: an HTTP version header equal to the envelope version passes rung 3."""
    result = classify_inbound_request(envelope(), headers={MCP_PROTOCOL_VERSION_HEADER: MODERN})
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


# --- all rungs pass ------------------------------------------------------------


def test_all_rungs_pass_yields_route() -> None:
    """Spec-mandated: a complete envelope at a supported version with agreeing header routes, surfacing the envelope."""
    result = classify_inbound_request(envelope(), headers={MCP_PROTOCOL_VERSION_HEADER: MODERN})
    assert isinstance(result, InboundModernRoute)
    assert result.protocol_version == MODERN
    assert result.client_info == CLIENT_INFO
    assert result.client_capabilities == CLIENT_CAPS


@pytest.mark.parametrize("method", ["initialize", "myorg/custom", "does/not/exist"])
def test_classifier_passes_unknown_method_through_to_route(method: str) -> None:
    """SDK-defined: the classifier does not gate on method — kernel dispatch is the single owner of that decision."""
    result = classify_inbound_request(envelope(method), headers={MCP_PROTOCOL_VERSION_HEADER: MODERN})
    assert isinstance(result, InboundModernRoute)


def test_ladder_first_failure_wins() -> None:
    """Spec-mandated: rungs evaluate in order — header-mismatch and version-unsupported
    would both fail; the header rung fires first so an inconsistent client is told it
    disagrees with itself rather than that its body version is unsupported."""
    body = envelope(version=LATEST_HANDSHAKE_VERSION)
    result = classify_inbound_request(body, headers={MCP_PROTOCOL_VERSION_HEADER: MODERN})
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
