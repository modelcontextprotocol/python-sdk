"""Shared fixtures for the interaction suite."""

from functools import partial

import pytest

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
    """Parametrize `connect` from the test's stacked `@requirement` marks (see `compute_cells`)."""
    if "connect" not in metafunc.fixturenames:
        return
    requirements = [REQUIREMENTS[mark.args[0]] for mark in metafunc.definition.iter_markers("requirement")]
    metafunc.parametrize("connect", compute_cells(requirements), indirect=True)


@pytest.fixture
def connect(request: pytest.FixtureRequest) -> Connect:
    """Transport-parametrized connection factory: a test using it runs once per matrix cell.

    Transport-tied tests (wire recording, bare ClientSession, transports/) connect directly instead.
    """
    transport, spec_version = request.param
    assert isinstance(transport, str)
    assert isinstance(spec_version, str)
    return partial(_FACTORIES[transport], spec_version=spec_version)
