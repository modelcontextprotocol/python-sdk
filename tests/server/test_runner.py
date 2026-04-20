"""Tests for `ServerRunner`.

End-to-end over `DirectDispatcher` with a real lowlevel `Server` as the
registry. Covers `_on_request` routing, the initialize handshake, the
init-gate, and that handlers receive a fully-built `Context`.
"""

from typing import Any

import anyio
import pytest

from mcp.server.connection import Connection
from mcp.server.context import Context
from mcp.server.lowlevel.server import Server
from mcp.server.runner import ServerRunner
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.exceptions import MCPError
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    Tool,
)

from ..shared.test_dispatcher import Recorder, echo_handlers


def _initialize_params() -> dict[str, Any]:
    return InitializeRequestParams(
        protocol_version=LATEST_PROTOCOL_VERSION,
        capabilities=ClientCapabilities(),
        client_info=Implementation(name="test-client", version="1.0"),
    ).model_dump(by_alias=True, exclude_none=True)


_seen_ctx: list[Context[Any, TransportContext]] = []
SrvT = Server[dict[str, Any]]


@pytest.fixture
def server() -> SrvT:
    """A lowlevel Server with one tools/list handler registered."""
    _seen_ctx.clear()

    async def list_tools(ctx: Any, params: Any) -> Any:
        # ctx is typed `Any` because Server's on_list_tools kwarg expects the
        # legacy ServerRequestContext shape; ServerRunner passes the new
        # `Context`. The transition is intentional — Handler is loosely typed.
        _seen_ctx.append(ctx)
        return {"tools": [Tool(name="t", input_schema={"type": "object"}).model_dump(by_alias=True)]}

    return Server(name="test-server", version="0.0.1", on_list_tools=list_tools)


@pytest.mark.anyio
async def test_runner_handles_initialize_and_populates_connection(server: SrvT):
    client, server_d = create_direct_dispatcher_pair()
    runner = ServerRunner(
        server=server,
        dispatcher=server_d,
        lifespan_state=None,
        has_standalone_channel=True,
    )
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(server_d.run, runner._on_request, runner._on_notify)
        with anyio.fail_after(5):
            result = await client.send_raw_request("initialize", _initialize_params())
        assert result["serverInfo"]["name"] == "test-server"
        assert "tools" in result["capabilities"]
        assert runner.connection.client_info is not None
        assert runner.connection.client_info.name == "test-client"
        assert runner.connection.protocol_version == LATEST_PROTOCOL_VERSION
        assert runner._initialized is True
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_runner_gates_requests_before_initialize(server: SrvT):
    client, server_d = create_direct_dispatcher_pair()
    runner = ServerRunner(server=server, dispatcher=server_d, lifespan_state=None, has_standalone_channel=True)
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(server_d.run, runner._on_request, runner._on_notify)
        with anyio.fail_after(5):
            with pytest.raises(MCPError) as exc:
                await client.send_raw_request("tools/list", None)
            assert exc.value.error.code == INVALID_REQUEST
            # ping is exempt
            assert await client.send_raw_request("ping", None) == {}
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_runner_routes_to_handler_after_initialize_and_builds_context(server: SrvT):
    client, server_d = create_direct_dispatcher_pair()
    runner = ServerRunner(server=server, dispatcher=server_d, lifespan_state=None, has_standalone_channel=True)
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(server_d.run, runner._on_request, runner._on_notify)
        with anyio.fail_after(5):
            await client.send_raw_request("initialize", _initialize_params())
            result = await client.send_raw_request("tools/list", None)
        assert result["tools"][0]["name"] == "t"
        ctx = _seen_ctx[0]
        assert isinstance(ctx, Context)
        assert ctx.lifespan is None
        assert isinstance(ctx.connection, Connection)
        assert ctx.transport.kind == "direct"
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_runner_unknown_method_raises_method_not_found(server: SrvT):
    client, server_d = create_direct_dispatcher_pair()
    runner = ServerRunner(server=server, dispatcher=server_d, lifespan_state=None, has_standalone_channel=True)
    runner._initialized = True  # bypass gate for this test
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(server_d.run, runner._on_request, runner._on_notify)
        with anyio.fail_after(5):
            with pytest.raises(MCPError) as exc:
                await client.send_raw_request("nonexistent/method", None)
            assert exc.value.error.code == METHOD_NOT_FOUND
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_runner_stateless_skips_init_gate(server: SrvT):
    client, server_d = create_direct_dispatcher_pair()
    runner = ServerRunner(
        server=server,
        dispatcher=server_d,
        lifespan_state=None,
        has_standalone_channel=False,
        stateless=True,
    )
    c_req, c_notify = echo_handlers(Recorder())
    async with anyio.create_task_group() as tg:
        await tg.start(client.run, c_req, c_notify)
        await tg.start(server_d.run, runner._on_request, runner._on_notify)
        with anyio.fail_after(5):
            result = await client.send_raw_request("tools/list", None)
        assert result["tools"][0]["name"] == "t"
        tg.cancel_scope.cancel()
