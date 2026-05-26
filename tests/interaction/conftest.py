"""Shared fixtures for the interaction suite."""

import pytest

from tests.interaction._connect import Connect, connect_in_memory, connect_over_sse, connect_over_streamable_http

_FACTORIES: dict[str, Connect] = {
    "in-memory": connect_in_memory,
    "streamable-http": connect_over_streamable_http,
    "sse": connect_over_sse,
}


@pytest.fixture(params=sorted(_FACTORIES))
def connect(request: pytest.FixtureRequest) -> Connect:
    """The transport-parametrized connection factory: a test using it runs once per transport.

    Tests that are tied to one transport (the wire-recording tests, the bare-ClientSession tests,
    the transport-specific tests under transports/) do not use this fixture and connect directly.
    """
    transport_name = request.param
    assert isinstance(transport_name, str)
    return _FACTORIES[transport_name]
