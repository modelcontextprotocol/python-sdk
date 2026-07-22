"""Shared fixtures for the interaction suite.

The ``connect`` fixture is parametrized per-test from the ``@requirement`` marks the test
carries: ``pytest_generate_tests`` looks up each cited requirement in the manifest and computes
the (transport, spec_version) cells via :func:`compute_cells`, applying arm exclusions, version
bounds, and known-failure xfails declaratively.
"""

from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from mcp_types import SERVER_INFO_META_KEY
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from mcp.client.client import Client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from tests._stamp import R, Unstamp
from tests._stamp import unstamped as _strip_required_stamp
from tests.interaction._connect import (
    Connect,
    connect_in_memory,
    connect_over_sse,
    connect_over_streamable_http,
    connect_over_streamable_http_stateless,
)
from tests.interaction._requirements import REQUIREMENTS, compute_cells

_FACTORIES: dict[str, Connect] = {
    "in-memory": connect_in_memory,
    "streamable-http": connect_over_streamable_http,
    "streamable-http-stateless": connect_over_streamable_http_stateless,
    "sse": connect_over_sse,
}


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``connect`` from the test's stacked ``@requirement`` marks."""
    if "connect" not in metafunc.fixturenames:
        return
    requirements = [REQUIREMENTS[mark.args[0]] for mark in metafunc.definition.iter_markers("requirement")]
    metafunc.parametrize("connect", compute_cells(requirements), indirect=True)


class CellConnect:
    """The cell's connection factory, also naming the cell's `spec_version`.

    Callable exactly like the `Connect` factories it wraps; the attribute lets
    sibling fixtures (`unstamped`) key on the cell's era without re-deriving it.
    """

    def __init__(self, factory: Connect, spec_version: str) -> None:
        self._factory = factory
        self.spec_version = spec_version

    def __call__(self, server: Server | MCPServer, **kwargs: Any) -> AbstractAsyncContextManager[Client]:
        # The matrix compares exact result payloads, and the 2026-era serverInfo
        # `_meta` stamp carries the server version, which defaults to the
        # commit-dependent installed package version. Pin it so expected
        # payloads stay deterministic across commits.
        lowlevel = server._lowlevel_server if isinstance(server, MCPServer) else server
        if lowlevel.version is None:
            lowlevel.version = "1.0.0"
        return self._factory(server, spec_version=self.spec_version, **kwargs)


@pytest.fixture
def connect(request: pytest.FixtureRequest) -> CellConnect:
    """The transport-parametrized connection factory: a test using it runs once per matrix cell.

    Tests that are tied to one transport (the wire-recording tests, the bare-ClientSession tests,
    the transport-specific tests under transports/) do not use this fixture and connect directly.
    """
    transport, spec_version = request.param
    assert isinstance(transport, str)
    assert isinstance(spec_version, str)
    return CellConnect(_FACTORIES[transport], spec_version)


@pytest.fixture
def unstamped(connect: CellConnect) -> Unstamp:
    """The cell's era-aware serverInfo-stamp normalizer, for full-result comparisons.

    On a modern cell the stamp MUST be present (asserted) and is stripped so
    one expected payload stays valid across eras; on a handshake-era cell the
    result must not be stamped at all. Either direction failing is a runner
    regression, so the same comparison line enforces both.
    """
    if connect.spec_version in MODERN_PROTOCOL_VERSIONS:
        return _strip_required_stamp

    def _assert_never_stamped(result: R) -> R:
        meta = result.meta
        assert meta is None or SERVER_INFO_META_KEY not in meta, "handshake-era results are never stamped"
        return result

    return _assert_never_stamped
