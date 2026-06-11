"""Tests for the deprecation warnings on the experimental tasks entry points."""

import warnings

import pytest

import mcp.types as types
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.client.session import ClientSession
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.memory import create_client_server_memory_streams, create_connected_server_and_client_session

_DEPRECATION_MATCH = "The experimental tasks API is deprecated"


@pytest.mark.anyio
async def test_client_session_experimental_property_is_deprecated() -> None:
    async with create_client_server_memory_streams() as (client_streams, _):
        read_stream, write_stream = client_streams
        session = ClientSession(read_stream, write_stream)
        with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):
            features = session.experimental
        # The cached path warns as well
        with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):
            assert session.experimental is features


@pytest.mark.anyio
async def test_client_session_experimental_task_handlers_kwarg_is_deprecated() -> None:
    async with create_client_server_memory_streams() as (client_streams, _):
        read_stream, write_stream = client_streams
        with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):
            ClientSession(read_stream, write_stream, experimental_task_handlers=ExperimentalTaskHandlers())


@pytest.mark.anyio
async def test_server_session_experimental_property_is_deprecated() -> None:
    init_options = InitializationOptions(
        server_name="test-server",
        server_version="0.1.0",
        capabilities=types.ServerCapabilities(),
    )
    async with create_client_server_memory_streams() as (_, server_streams):
        read_stream, write_stream = server_streams
        async with ServerSession(read_stream, write_stream, init_options) as session:
            with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):
                features = session.experimental
            # The cached path warns as well. coverage.py misreports the branch arcs of the
            # last statement in a nested `async with` body on Python 3.11+.
            with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):  # pragma: no branch
                assert session.experimental is features


def test_lowlevel_server_experimental_property_is_deprecated() -> None:
    server: Server = Server("test-server")
    with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):
        handlers = server.experimental
    # The cached path warns as well
    with pytest.warns(DeprecationWarning, match=_DEPRECATION_MATCH):
        assert server.experimental is handlers


@pytest.mark.anyio
async def test_plain_session_usage_does_not_warn() -> None:
    """Clients and servers that don't touch the tasks API must not see deprecation warnings."""
    server: Server = Server("test-server")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        async with create_connected_server_and_client_session(server) as session:
            await session.send_ping()
