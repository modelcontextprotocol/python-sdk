"""Application lifespan and connection supervision for custom transports."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Generic

import anyio
import anyio.abc
from typing_extensions import TypeVar

from mcp.server.runner import serve_dual_era_loop, serve_modern_dispatcher
from mcp.shared._compat import resync_tracer
from mcp.shared.transport import DispatcherTransport, Transport, TransportContextBuilder

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

__all__ = ["ServerRuntime"]

logger = logging.getLogger(__name__)
LifespanT = TypeVar("LifespanT")


@dataclass
class ServerRuntime(Generic[LifespanT]):
    """An active server returned by `Server.serve()` or `MCPServer.serve()`.

    Each `connect()` call serves a peer with independent protocol and request-ID state.
    """

    _server: Server[LifespanT]
    _lifespan_state: LifespanT
    _task_group: anyio.abc.TaskGroup
    _limiter: anyio.CapacityLimiter
    _active: bool = field(default=True, init=False)

    @classmethod
    @asynccontextmanager
    async def open(
        cls, server: Server[LifespanT], *, max_connections: int = 100
    ) -> AsyncIterator[ServerRuntime[LifespanT]]:
        """Share one lifespan, closing connections before application cleanup.

        Cleanup has a five-second cancellation deadline per layer and must cooperate.
        """
        if max_connections < 1:
            raise ValueError("max_connections must be positive")
        body_error: BaseException | None = None
        with anyio.CancelScope() as lifespan_scope:
            async with server.lifespan(server) as state:
                try:
                    async with anyio.create_task_group() as tg:
                        runtime = cls(server, state, tg, anyio.CapacityLimiter(max_connections))
                        try:
                            yield runtime
                        finally:
                            runtime._active = False
                            tg.cancel_scope.cancel()
                except BaseException as exc:
                    body_error = exc
                    raise
                finally:
                    lifespan_scope.shield = True
                    lifespan_scope.deadline = anyio.current_time() + 5
        if lifespan_scope.cancelled_caught:
            logger.warning("Server lifespan cleanup exceeded five seconds")
            if body_error is not None:
                raise body_error
        await resync_tracer()

    async def connect(
        self,
        transport: Transport | DispatcherTransport,
        *,
        session_id: str | None = None,
        transport_builder: TransportContextBuilder | None = None,
    ) -> None:
        """Open and supervise one peer's transport until it disconnects.

        Waits for capacity, then owns the entered transport. Opening failures reach
        the caller; later failures are logged and isolated. After return, caller
        cancellation does not close the connection.
        Dispatcher transports signal readiness through `Dispatcher.run()`;
        message transports return before receiving the first MCP request.

        Args:
            transport: An unopened message transport or `DispatcherTransport`.
            session_id: Optional identity for a handshake-era connection.
            transport_builder: Builds handler metadata for each inbound message.

        Raises:
            RuntimeError: If this runtime has closed.
        """
        if not self._active:
            raise RuntimeError("Server runtime is closed")
        if isinstance(transport, DispatcherTransport) and (session_id is not None or transport_builder is not None):
            raise ValueError("Dispatcher transports supply their own context and do not use handshake-era sessions")

        async def serve(*, task_status: anyio.abc.TaskStatus[None]) -> None:
            ready = False
            run_error: BaseException | None = None

            class ReadyStatus:
                def started(self, value: None = None) -> None:
                    nonlocal ready
                    task_status.started()
                    ready = True

            status = ReadyStatus()
            try:
                async with self._limiter:
                    with anyio.CancelScope() as cleanup_scope:
                        async with AsyncExitStack() as stack:
                            if isinstance(transport, DispatcherTransport):
                                dispatcher = await stack.enter_async_context(transport.connection)
                                run = partial(
                                    serve_modern_dispatcher,
                                    self._server,
                                    dispatcher,
                                    lifespan_state=self._lifespan_state,
                                    task_status=status,
                                )
                            else:
                                read, write = await stack.enter_async_context(transport)
                                run = partial(
                                    serve_dual_era_loop,
                                    self._server,
                                    read,
                                    write,
                                    lifespan_state=self._lifespan_state,
                                    session_id=session_id,
                                    transport_builder=transport_builder,
                                )
                            try:
                                if not isinstance(transport, DispatcherTransport):
                                    status.started()
                                await run()
                            except BaseException as exc:
                                run_error = exc
                                raise
                            finally:
                                cleanup_scope.shield = True
                                cleanup_scope.deadline = anyio.current_time() + 5
                    if cleanup_scope.cancelled_caught:
                        logger.warning("Transport cleanup exceeded five seconds")
                        if run_error is not None:
                            raise run_error
                    return
            except Exception:
                if not ready:
                    raise
                logger.exception("Transport connection failed")

        await self._task_group.start(serve)
