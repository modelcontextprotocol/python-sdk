"""Serving a `Server` over a duplex message stream (stdio, SSE, custom sockets).

`serve_stream` is the driver for stream transports. The client's opening
messages decide the connection's protocol era, in receive order, among those
`Server(posture=)` offers, and that era serves every later message; `Posture`
names which eras a server offers at all.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Mapping
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, Literal

import anyio
import anyio.abc
from mcp_types import INVALID_REQUEST
from mcp_types.version import LATEST_MODERN_VERSION
from typing_extensions import TypeVar

from mcp.server.connection import Connection, NotifyOnlyOutbound
from mcp.server.models import InitializationOptions
from mcp.server.runner import ServerRunner, aclose_shielded, serve_one
from mcp.server.stdio import newline_json_transport
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import Admission, DispatchContext
from mcp.shared.exceptions import MCPError
from mcp.shared.inbound import InboundLadderRejection, classify_inbound_request, has_envelope_intent
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import MessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

__all__ = ["Posture", "serve_listener", "serve_stream"]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)

_EOF_DRAIN_WINDOW: float = 2
"""Seconds to let in-flight work drain after the peer closes our input."""

_HANDSHAKE_NOTIFICATION = "notifications/initialized"
"""The one notification that completes a legacy handshake and so opens the legacy era."""


class Posture(Enum):
    """Which protocol eras a server offers on a connection; `DUAL` lets the opening message decide."""

    DUAL = "dual"
    """Both eras: the legacy `initialize` handshake and the modern per-request envelope."""

    LEGACY_ONLY = "legacy-only"
    """Only the legacy `initialize` handshake era."""

    MODERN_ONLY = "modern-only"
    """Only the modern per-request-envelope era (2026-07-28+)."""


class _Unset:
    """Sentinel type for an omitted `lifespan_state` (`None` is a valid state)."""


_UNSET = _Unset()


async def _refuse(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """The body of a request the connection's era refuses: raising is its whole answer."""
    raise MCPError(code=code, message=message, data=data)


def _opening_intent(method: str, params: Mapping[str, Any] | None) -> Literal["legacy", "modern", "probe"]:
    """The era an undecided connection's opening request declares; `initialize` is always legacy."""
    if method == "initialize" or not has_envelope_intent(params):
        return "legacy"
    return "probe" if method == "server/discover" else "modern"


class _LegacyEra(Generic[LifespanT]):
    """The handshake (2025) era of a stream connection: the loop kernel over the shared dispatcher.

    Refuses envelope-carrying requests (except `initialize`) with `INVALID_REQUEST`
    rather than serving an era-ambiguous method under legacy semantics.
    """

    def __init__(self, runner: ServerRunner[LifespanT]) -> None:
        self.runner = runner

    def on_request(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> Awaitable[dict[str, Any]]:
        if method != "initialize" and has_envelope_intent(params):
            return _refuse(
                INVALID_REQUEST,
                "connection speaks the legacy handshake era; modern per-request-envelope requests are not accepted",
            )
        return self.runner.on_request(dctx, method, params)

    def on_notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> Awaitable[None]:
        return self.runner.on_notify(dctx, method, params)


class _ModernEra(Generic[LifespanT]):
    """The modern (2026-07-28+) era of a stream connection.

    Every request is a single exchange served through `serve_one` with a born-ready
    per-request `Connection`; server-initiated requests are refused.
    """

    def __init__(self, server: Server[LifespanT], lifespan_state: LifespanT, outbound: NotifyOnlyOutbound) -> None:
        self._server = server
        self._lifespan_state = lifespan_state
        self._outbound = outbound

    def on_request(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> Awaitable[dict[str, Any]]:
        return self._serve(dctx, method, params)

    def on_notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> Awaitable[None]:
        return self._notify(dctx, method, params)

    async def _serve(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        route = classify_inbound_request({"method": method, "params": params})
        if isinstance(route, InboundLadderRejection):
            raise MCPError(code=route.code, message=route.message, data=route.data)
        connection = Connection.from_envelope(
            route.protocol_version, route.client_info, route.client_capabilities, outbound=self._outbound
        )
        return await serve_one(
            self._server, dctx, method, params, connection=connection, lifespan_state=self._lifespan_state
        )

    async def _notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> None:
        # Notifications carry no envelope, so they take the era's (single) modern version.
        connection = Connection.from_envelope(LATEST_MODERN_VERSION, None, None, outbound=self._outbound)
        runner = ServerRunner(self._server, connection, self._lifespan_state)
        try:
            await runner.on_notify(dctx, method, params)
        finally:
            await aclose_shielded(connection)


async def _ignore_stray_notification() -> None:
    """The body of a notification that opened nothing on an undecided connection: it is ignored."""


class _StreamConnection(Generic[LifespanT]):
    """One duplex stream connection: admits every message and routes it to the connection's era.

    `_era` starts from the server's posture and, under `DUAL`, is decided once, in
    receive order, by the first era-distinctive message the dispatcher admits.
    """

    def __init__(
        self,
        server: Server[LifespanT],
        read_stream: ReadStream[SessionMessage | Exception],
        write_stream: WriteStream[SessionMessage],
        *,
        posture: Posture,
        lifespan_state: LifespanT,
        init_options: InitializationOptions | None,
        session_id: str | None,
        raise_exceptions: bool,
    ) -> None:
        self._server = server
        self._dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
            read_stream,
            write_stream,
            transport_builder=self._transport_context,
            raise_handler_exceptions=raise_exceptions,
            on_read_eof=self._drain,
        )
        loop_connection = Connection.for_loop(self._dispatcher, session_id=session_id)
        self._legacy: _LegacyEra[LifespanT] = _LegacyEra(
            ServerRunner(server, loop_connection, lifespan_state, init_options=init_options)
        )
        self._modern: _ModernEra[LifespanT] = _ModernEra(server, lifespan_state, NotifyOnlyOutbound(self._dispatcher))
        # Posture is consumed here, once: which eras exist for this connection.
        starting_era: dict[Posture, _LegacyEra[LifespanT] | _ModernEra[LifespanT] | None] = {
            Posture.DUAL: None,
            Posture.LEGACY_ONLY: self._legacy,
            Posture.MODERN_ONLY: self._modern,
        }
        self._era: _LegacyEra[LifespanT] | _ModernEra[LifespanT] | None = starting_era[posture]

    def _transport_context(self, _metadata: MessageMetadata) -> TransportContext:
        # Admission has already decided this frame's era; only the legacy era
        # allows server-initiated requests (the modern protocol forbids them).
        return TransportContext(kind="jsonrpc", can_send_request=self._era is self._legacy)

    async def run(self, *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        try:
            await self._dispatcher.run(
                self._on_request,
                self._on_notify,
                self._admit_notification,
                admit=self._admit,
                task_status=task_status,
            )
        finally:
            await aclose_shielded(self._legacy.runner.connection)

    def _admit(self, method: str, params: Mapping[str, Any] | None) -> Admission:
        """Admit one request in receive order, deciding the era before its transport context is built.

        `initialize` holds the read loop so requests pipelined behind it see the committed handshake.
        """
        self._era_for(method, params)
        return Admission(self._on_request, hold=method == "initialize")

    def _era_for(self, method: str, params: Mapping[str, Any] | None) -> _LegacyEra[LifespanT] | _ModernEra[LifespanT]:
        """The era that serves this request; the connection's era is decided by its opening request."""
        if self._era is not None:
            return self._era
        intent = _opening_intent(method, params)
        if intent == "probe":
            # Answered with modern semantics; the connection stays undecided.
            return self._modern
        self._era = self._legacy if intent == "legacy" else self._modern
        return self._era

    def _admit_notification(self, method: str, params: Mapping[str, Any] | None) -> bool:
        """Notification-side sibling of `_admit`: only the bare handshake notification opens
        (the legacy) era. Never consumes; `_on_notify` serves the frame afterwards."""
        if self._era is None and method == _HANDSHAKE_NOTIFICATION:
            self._era = self._legacy
        return False

    def _on_request(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> Awaitable[dict[str, Any]]:
        return self._era_for(method, params).on_request(dctx, method, params)

    def _on_notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> Awaitable[None]:
        if self._era is None:
            # A stray notification on an undecided connection is ignored (the spec's word).
            logger.debug("ignored stray notification %s on an undecided connection", method)
            return _ignore_stray_notification()
        return self._era.on_notify(dctx, method, params)

    async def _drain(self) -> None:
        """The peer closed our input: close listen streams, then let in-flight work end
        gracefully within `_EOF_DRAIN_WINDOW`, while the output is still up."""
        self._server.close_subscriptions()
        with anyio.move_on_after(_EOF_DRAIN_WINDOW, shield=True):
            await self._dispatcher.wait_for_in_flight()


async def serve_stream(
    server: Server[LifespanT],
    read_stream: ReadStream[SessionMessage | Exception],
    write_stream: WriteStream[SessionMessage],
    *,
    initialization_options: InitializationOptions | None = None,
    lifespan_state: LifespanT | _Unset = _UNSET,
    raise_exceptions: bool = False,
    task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Serve `server` over a duplex message stream until the read side closes.

    The driver for stream transports: the client's opening messages decide the
    connection's era among those `server.posture` offers. Enters
    `server.lifespan()` unless `lifespan_state` is given.

    Args:
        initialization_options: The legacy handshake's `InitializeResult`
            payload; defaults to `server.create_initialization_options()`.
        lifespan_state: An already-entered lifespan state, for several
            connections sharing one lifespan.
        raise_exceptions: Also re-raise handler exceptions out of this call
            after the peer has been answered (an in-process testing aid).
    """
    if isinstance(lifespan_state, _Unset):
        async with server.lifespan() as state:
            await serve_stream(
                server,
                read_stream,
                write_stream,
                initialization_options=initialization_options,
                lifespan_state=state,
                raise_exceptions=raise_exceptions,
                task_status=task_status,
            )
        return
    connection = _StreamConnection(
        server,
        read_stream,
        write_stream,
        posture=server.posture,
        lifespan_state=lifespan_state,
        init_options=initialization_options,
        session_id=None,
        raise_exceptions=raise_exceptions,
    )
    await connection.run(task_status=task_status)


async def serve_legacy_stream(
    server: Server[LifespanT],
    read_stream: ReadStream[SessionMessage | Exception],
    write_stream: WriteStream[SessionMessage],
    *,
    lifespan_state: LifespanT,
    session_id: str | None = None,
) -> None:
    """Serve a stream the transport has already routed to the legacy handshake era.

    Transport-internal (the streamable-HTTP manager's stateful sessions are
    born legacy); not part of the author-facing surface.
    """
    connection = _StreamConnection(
        server,
        read_stream,
        write_stream,
        posture=Posture.LEGACY_ONLY,
        lifespan_state=lifespan_state,
        init_options=None,
        session_id=session_id,
        raise_exceptions=False,
    )
    await connection.run()


async def serve_listener(server: Server[LifespanT], listener: anyio.abc.Listener[anyio.abc.ByteStream]) -> None:
    """Serve every connection `listener` accepts, over the stdio wire, until cancelled.

    Enters the server's lifespan once (shared by every connection), frames each
    accepted byte stream with `newline_json_transport`, and drives it with
    `serve_stream`; takes ownership of `listener` and closes it on the way out.

        listener = await anyio.create_unix_listener("/tmp/mcp.sock")
        await serve_listener(server, listener)

    Caveat: `subscriptions/listen` streams belong to the shared `server`, so
    one connection's disconnect gracefully ends the open listen streams of
    every connection this server is serving.
    """
    async with listener, server.lifespan() as lifespan_state:

        async def handle(stream: anyio.abc.ByteStream) -> None:
            # Accepted here, so closed here.
            async with stream, newline_json_transport(stream) as (read_stream, write_stream):
                await serve_stream(server, read_stream, write_stream, lifespan_state=lifespan_state)

        await listener.serve(handle)
