"""Factories for the experimental native protobuf transport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import grpc.aio
from mcp.shared.dispatcher import Dispatcher
from mcp.shared.transport import DispatcherTransport, TransportContext

from mcp_transport_examples.grpc_client import GRPCClientDispatcher
from mcp_transport_examples.grpc_server import GRPCServerDispatcher


def grpc_client(channel: grpc.aio.Channel) -> DispatcherTransport:
    """Use a borrowed channel with `Client`; the caller owns TLS, credentials, and channel closure."""

    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        yield GRPCClientDispatcher(channel)

    return DispatcherTransport(connection())


def grpc_server(server: grpc.aio.Server, *, max_requests: int = 64) -> DispatcherTransport:
    """Attach one MCP binding to a borrowed server before starting its listener.

    Connect this transport to `ServerRuntime`, then start the gRPC server.
    The caller owns the listener and other registered gRPC services. Runtime
    shutdown cancels MCP handlers without stopping unrelated services.
    """

    @asynccontextmanager
    async def connection() -> AsyncIterator[Dispatcher[TransportContext]]:
        yield GRPCServerDispatcher(server, max_requests=max_requests)

    return DispatcherTransport(connection())
