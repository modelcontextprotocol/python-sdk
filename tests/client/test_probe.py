"""Unit tests for the connect-time auto-negotiation policy (`mcp.client._probe.negotiate_auto`).

`negotiate_auto` is a small policy function that drives a `ClientSession` through the
``server/discover`` probe and decides between ``adopt()`` (modern), ``initialize()`` (legacy
fallback), or letting the probe's exception propagate. The policy is a *denylist*: every
``MCPError`` falls back to ``initialize()``, the sole exception being -32022 with a disjoint
modern-only ``supported`` list. Any non-``MCPError`` exception (network errors, anyio
resource errors) propagates untouched — an outage is never an era verdict.

These tests pin the classifier in isolation with a stub session; the end-to-end wire shape is
covered by ``tests/interaction/lowlevel/test_client_connect.py``.
"""

from __future__ import annotations

from typing import Any, cast

import anyio
import httpx2
import mcp_types as types
import pytest
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
    Implementation,
    ServerCapabilities,
)
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_MODERN_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)

from mcp.client._probe import _parse_supported, negotiate_auto
from mcp.client.session import ClientSession
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio


class _StubSession:
    """Minimal stand-in for `ClientSession` exposing only what `negotiate_auto` touches.

    `send_discover` plays back a script (raise an exception, or return a dict);
    `initialize` and `adopt` just record that they were called.
    """

    def __init__(self, *script: dict[str, Any] | Exception) -> None:
        self._script: list[dict[str, Any] | Exception] = list(script)
        self.probed_at: list[str] = []
        self.initialized: bool = False
        self.adopted: types.DiscoverResult | None = None

    async def send_discover(self, version: str) -> dict[str, Any]:
        self.probed_at.append(version)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def initialize(self) -> None:
        self.initialized = True

    def adopt(self, result: types.DiscoverResult) -> None:
        self.adopted = result


async def _negotiate(session: _StubSession) -> None:
    """Drive `negotiate_auto` against the stub; cast at one seam so the tests stay suppression-free."""
    await negotiate_auto(cast("ClientSession", session))


def _discover_dict(versions: list[str] | None = None) -> dict[str, Any]:
    return types.DiscoverResult(
        supported_versions=versions or list(MODERN_PROTOCOL_VERSIONS),
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="stub", version="0"),
    ).model_dump(by_alias=True, mode="json", exclude_none=True)


def _err_32022(supported: Any) -> MCPError:
    return MCPError(
        code=UNSUPPORTED_PROTOCOL_VERSION,
        message="unsupported protocol version",
        data={"supported": supported, "requested": LATEST_MODERN_VERSION},
    )


# --- happy path: modern server ---


async def test_a_valid_discover_result_is_adopted_without_initializing() -> None:
    """A parseable `DiscoverResult` from the probe is adopted; `initialize()` is never called."""
    session = _StubSession(_discover_dict())
    await _negotiate(session)
    assert session.adopted is not None
    assert session.adopted.server_info.name == "stub"
    assert not session.initialized
    assert session.probed_at == [LATEST_MODERN_VERSION]


async def test_an_unparseable_discover_result_falls_back_to_initialize() -> None:
    """A probe response that does not validate as `DiscoverResult` is not modern evidence,
    so the policy falls back to the legacy handshake instead of adopting garbage."""
    session = _StubSession({"not": "a discover result"})
    await _negotiate(session)
    assert session.initialized
    assert session.adopted is None


# --- the denylist: every JSON-RPC error code falls back ---


@pytest.mark.parametrize(
    "code",
    [
        pytest.param(METHOD_NOT_FOUND, id="method-not-found-32601"),
        pytest.param(INVALID_REQUEST, id="invalid-request-32600"),
        pytest.param(INTERNAL_ERROR, id="internal-error-32603"),
        pytest.param(PARSE_ERROR, id="parse-error-32700"),
    ],
)
async def test_any_jsonrpc_error_from_the_probe_falls_back_to_initialize(code: int) -> None:
    """The denylist: every server-sent JSON-RPC error code is treated as "not modern" and
    triggers the legacy `initialize()` handshake. Legacy servers reject the unknown
    ``server/discover`` method with various codes (-32601, -32600, -32603, -32700) depending
    on where in their pipeline the request bounces."""
    session = _StubSession(MCPError(code=code, message="nope"))
    await _negotiate(session)
    assert session.initialized
    assert session.adopted is None
    assert session.probed_at == [LATEST_MODERN_VERSION]


# --- -32022 corrective retry ---


async def test_unsupported_version_with_a_mutual_modern_version_retries_once_then_adopts() -> None:
    """-32022 with a `supported` list naming a modern version we speak: re-probe once at
    the highest mutual version, then adopt the second response."""
    session = _StubSession(_err_32022(list(MODERN_PROTOCOL_VERSIONS)), _discover_dict())
    await _negotiate(session)
    assert session.probed_at == [LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS[-1]]
    assert session.adopted is not None
    assert not session.initialized


async def test_unsupported_version_naming_only_handshake_versions_falls_back_to_initialize() -> None:
    """-32022 with `supported` naming only handshake-era versions: the server is reachable
    via the legacy handshake, so fall back rather than raise."""
    session = _StubSession(_err_32022(list(HANDSHAKE_PROTOCOL_VERSIONS)))
    await _negotiate(session)
    assert session.initialized
    assert session.adopted is None
    assert session.probed_at == [LATEST_MODERN_VERSION]


async def test_unsupported_version_with_disjoint_modern_only_supported_reraises() -> None:
    """-32022 with `supported` naming only modern versions we *don't* speak: this is the
    one denylist exception — the server is modern-only and there is no mutual version, so
    falling back to `initialize()` would also fail. The original `MCPError` re-raises."""
    session = _StubSession(_err_32022(["2099-01-01"]))
    with pytest.raises(MCPError) as exc_info:
        await _negotiate(session)
    assert exc_info.value.code == UNSUPPORTED_PROTOCOL_VERSION
    assert not session.initialized
    assert session.adopted is None


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(None, id="no-data"),
        pytest.param({"supported": "not-a-list"}, id="malformed-supported"),
        pytest.param({"requested": LATEST_MODERN_VERSION}, id="missing-supported"),
    ],
)
async def test_unsupported_version_with_unparseable_data_falls_back_to_initialize(data: Any) -> None:
    """-32022 with no/malformed `error.data`: nothing actionable, so fall through to the
    denylist's `initialize()` fallback rather than guess or raise."""
    session = _StubSession(MCPError(code=UNSUPPORTED_PROTOCOL_VERSION, message="bad version", data=data))
    await _negotiate(session)
    assert session.initialized
    assert session.adopted is None
    assert session.probed_at == [LATEST_MODERN_VERSION]


async def test_a_second_unsupported_version_after_the_corrective_retry_does_not_loop() -> None:
    """The corrective -32022 retry happens at most once; a second -32022 naming a
    modern-only `supported` list re-raises rather than re-probing forever (the loop
    guard makes this the disjoint-modern case on attempt two)."""
    session = _StubSession(_err_32022(list(MODERN_PROTOCOL_VERSIONS)), _err_32022(list(MODERN_PROTOCOL_VERSIONS)))
    with pytest.raises(MCPError) as exc_info:
        await _negotiate(session)
    assert exc_info.value.code == UNSUPPORTED_PROTOCOL_VERSION
    assert session.probed_at == [LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS[-1]]
    assert not session.initialized
    assert session.adopted is None


# --- non-MCP errors propagate ---


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(httpx2.ConnectError("connection refused"), id="httpx2-connect-error"),
        pytest.param(anyio.ClosedResourceError(), id="anyio-closed-resource"),
    ],
)
async def test_a_network_or_resource_error_from_the_probe_propagates_unchanged(exc: Exception) -> None:
    """Anything that is not an `MCPError` propagates as-is; an outage or in-process bug
    is never an era verdict, and `initialize()` is not called."""
    session = _StubSession(exc)
    with pytest.raises(type(exc)):
        await _negotiate(session)
    assert not session.initialized
    assert session.adopted is None


# --- helper ---


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"supported": ["2026-07-28"], "requested": "x"}, ["2026-07-28"]),
        ({"supported": [], "requested": "x"}, []),
        (None, None),
        ({"supported": 123, "requested": "x"}, None),
        ("not a dict", None),
    ],
)
def test_parse_supported_returns_none_for_anything_not_shaped_like_the_spec_error_data(
    data: Any, expected: list[str] | None
) -> None:
    """`_parse_supported` returns the `supported` list when `error.data` validates as
    `UnsupportedProtocolVersionErrorData`, and `None` otherwise — never raises."""
    assert _parse_supported(data) == expected
