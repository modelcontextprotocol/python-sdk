from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeAlias, TypeVar

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import ServerSession
from mcp.server import InitializationOptions
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp_v2.types.json_rpc import (
    JSONRPCBase,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

T = TypeVar("T")
K = TypeVar("K")
ReqT = TypeVar("ReqT", bound=JSONRPCBase)
RespT = TypeVar("RespT", bound=JSONRPCResponse | None)


# Starlette-style lifespan type: receives server, yields state
Lifespan: TypeAlias = Callable[["LowLevelServer[T, Any]"], AbstractAsyncContextManager[T]]
SessionLifespan: TypeAlias = Callable[["LowLevelServer[Any, K]", "ServerSession"], AbstractAsyncContextManager[K]]


@asynccontextmanager
async def default_lifespan(server: "LowLevelServer[dict[str, Any], Any]") -> AsyncIterator[dict[str, Any]]:
    """Default lifespan that yields an empty dict."""
    yield {}


@asynccontextmanager
async def default_session_lifespan(
    server: "LowLevelServer[Any, dict[str, Any]]",
    session: "ServerSession",
) -> AsyncIterator[dict[str, Any]]:
    """Default session lifespan that yields an empty dict."""
    yield {}


@dataclass
class LowLevelContext(Generic[T]):
    stuff: T
    session: ServerSession
    request_context: RequestContext


class LowLevelHandler(Protocol[T, ReqT, RespT]):
    async def __call__(self, ctx: LowLevelContext[T], request: ReqT) -> RespT: ...


class LowLevelRequestHandler(LowLevelHandler[T, JSONRPCRequest, JSONRPCResponse]):
    pass


class LowLevelNotificationHandler(LowLevelHandler[T, JSONRPCNotification, None]):
    pass


class LowLevelServer(Generic[T, K]):
    def __init__(
        self,
        request_handler: LowLevelRequestHandler[T],
        notification_handler: LowLevelNotificationHandler[T],
        *,
        lifespan: Lifespan[T] = default_lifespan,  # type: ignore[assignment]
    ):
        self._request_handler = request_handler
        self._notification_handler = notification_handler
        self._lifespan = lifespan

    @property
    def lifespan(self) -> Lifespan[T]:
        """
        Starlette-style async context manager for server-level state.

        This runs ONCE for the entire lifetime of the server, NOT per-session.
        The yielded state is shared across all sessions and requests.

        Example:
            @asynccontextmanager
            async def lifespan(server: LowLevelServer) -> AsyncIterator[AppState]:
                db = await Database.connect()
                yield AppState(db=db)
                await db.close()
        """
        return self._lifespan

    async def send_request(self, context: LowLevelContext[T], request: JSONRPCRequest) -> JSONRPCResponse:  # or stream
        return await self._request_handler(context, request)

    async def send_notification(self, context: LowLevelContext[T], notification: JSONRPCNotification) -> None:
        await self._notification_handler(context, notification)


class LowLevelServerRunner(Generic[T, K]):
    """
    Runs a LowLevelServer with proper lifecycle management.

    The runner:
    - Enters the server's lifespan ONCE at startup
    - Can handle multiple sessions, all sharing the same lifespan state
    - Enters session_lifespan for each session
    - Exits the lifespan on shutdown

    Example:
        runner = LowLevelServerRunner(server)

        # Start the runner (enters server lifespan)
        async with runner.run() as r:
            # Handle sessions (can be called multiple times)
            await r.handle_session(read, write, init_opts)
    """

    def __init__(self, app: LowLevelServer[T, K]):
        self._app = app
        self._lifespan_state: T | None = None

    @asynccontextmanager
    async def run(self) -> AsyncIterator["LowLevelServerRunner[T, K]"]:
        """
        Start the runner, entering the server's lifespan.

        This should be called ONCE, and the runner can then handle multiple sessions.
        The lifespan state is shared across all sessions.

        Example:
            async with runner.run() as r:
                # For stdio (single session):
                await r.handle_session(read, write, init_opts)

                # For HTTP (multiple sessions):
                async for read, write in transport.accept():
                    task_group.start_soon(r.handle_session, read, write, init_opts)
        """
        async with self._app.lifespan(self._app) as state:
            self._lifespan_state = state
            yield self
            self._lifespan_state = None

    async def handle_session(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        initialization_options: InitializationOptions,
        *,
        raise_exceptions: bool = False,
        stateless: bool = False,
    ) -> None:
        """
        Handle a single session using the shared lifespan state.

        This can be called multiple times while the runner is active.
        Each session:
        - Shares the server-level lifespan state
        - Gets its own session-level lifespan state
        """
        if self._lifespan_state is None:
            raise RuntimeError("Runner not started. Use 'async with runner.run()' first.")

        async with AsyncExitStack() as stack:
            # Create the session
            session = await stack.enter_async_context(
                ServerSession(
                    read_stream,
                    write_stream,
                    initialization_options,
                    stateless=stateless,
                )
            )

            # Enter session-level lifespan
            session_state = await stack.enter_async_context(self._app.session_lifespan(self._app, session))

            # Build context with both lifespans
            context = LowLevelContext(
                stuff=self._lifespan_state,
                session=session,
                request_context=None,  # type: ignore[arg-type] # Will be set per-request
            )

            async with anyio.create_task_group() as tg:
                async for message in session.incoming_messages:
                    tg.start_soon(
                        self._handle_message,
                        message,
                        session,
                        context,
                    )

    async def _handle_message(
        self,
        message: Any,
        session: ServerSession,
        context: LowLevelContext[T],
        session_state: K,
        raise_exceptions: bool,
    ) -> None:
        """Handle a single message from the session."""
        # TODO: Dispatch based on message type (request vs notification)
        # This is a sketch - real implementation needs proper message handling
        pass
