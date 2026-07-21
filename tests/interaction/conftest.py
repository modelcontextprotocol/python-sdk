"""Shared fixtures for the interaction suite.

The ``connect`` fixture is parametrized per-test from the ``@requirement`` marks the test
carries: ``pytest_generate_tests`` looks up each cited requirement in the manifest and computes
the (transport, spec_version) cells via :func:`compute_cells`, applying arm exclusions, version
bounds, and known-failure xfails declaratively.
"""

from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest

from mcp.client.client import Client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
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


@pytest.fixture
def connect(request: pytest.FixtureRequest) -> Connect:
    """The transport-parametrized connection factory: a test using it runs once per matrix cell.

    Tests that are tied to one transport (the wire-recording tests, the bare-ClientSession tests,
    the transport-specific tests under transports/) do not use this fixture and connect directly.
    """
    transport, spec_version = request.param
    assert isinstance(transport, str)
    assert isinstance(spec_version, str)
    factory = _FACTORIES[transport]

    def _connect(server: Server | MCPServer, **kwargs: Any) -> AbstractAsyncContextManager[Client]:
        # The matrix compares exact result payloads, and the (default-on) 2026-era
        # serverInfo `_meta` stamp would bake the commit-dependent package version
        # into every snapshot. The matrix therefore runs with stamping off;
        # stamping itself has dedicated coverage in tests/server/.
        lowlevel = server._lowlevel_server if isinstance(server, MCPServer) else server
        lowlevel.include_server_info = False
        return factory(server, spec_version=spec_version, **kwargs)

    return _connect
