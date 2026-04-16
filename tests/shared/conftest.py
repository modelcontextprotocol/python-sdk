"""Shared fixtures for `Dispatcher` contract tests.

The `pair_factory` fixture parametrizes contract tests over every `Dispatcher`
implementation, so the same behavioral assertions run against `DirectDispatcher`
(in-memory) and `JSONRPCDispatcher` (over crossed anyio memory streams).
"""

from collections.abc import Callable

import anyio
import pytest

from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import Dispatcher
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import SessionMessage
from mcp.shared.transport_context import TransportContext

DispatcherTriple = tuple[Dispatcher[TransportContext], Dispatcher[TransportContext], Callable[[], None]]
PairFactory = Callable[..., DispatcherTriple]


def direct_pair(*, can_send_request: bool = True) -> DispatcherTriple:
    client, server = create_direct_dispatcher_pair(can_send_request=can_send_request)

    def close() -> None:
        client.close()
        server.close()

    return client, server, close


def jsonrpc_pair(*, can_send_request: bool = True) -> DispatcherTriple:
    """Two `JSONRPCDispatcher`s wired over crossed in-memory streams."""
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)

    def builder(_rid: object, _meta: object) -> TransportContext:
        return TransportContext(kind="jsonrpc", can_send_request=can_send_request)

    client: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(s2c_recv, c2s_send, transport_builder=builder)
    server: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(c2s_recv, s2c_send, transport_builder=builder)

    def close() -> None:
        for s in (c2s_send, c2s_recv, s2c_send, s2c_recv):
            s.close()

    return client, server, close


_JSONRPC_XFAIL = pytest.mark.xfail(
    strict=True,
    reason="JSONRPCDispatcher.run() not yet implemented (PR2 chunks b/c)",
)


@pytest.fixture(
    params=[
        pytest.param(direct_pair, id="direct"),
        pytest.param(jsonrpc_pair, id="jsonrpc", marks=_JSONRPC_XFAIL),
    ]
)
def pair_factory(request: pytest.FixtureRequest) -> PairFactory:
    return request.param


__all__ = ["PairFactory", "direct_pair", "jsonrpc_pair"]
