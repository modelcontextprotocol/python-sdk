"""`ServerRunner` - the per-connection handler kernel.

Bridges the dispatch layer (`on_request`/`on_notify`, untyped dicts) and the
user's typed handler layer. The free-function drivers (`serve_connection`,
`serve_loop`, `serve_one`) drive the dispatcher and tear down the
`Connection`; the entry constructs it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Mapping
from dataclasses import KW_ONLY, dataclass
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any, Generic, cast

import anyio
import anyio.abc
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    CacheableResult,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    RequestParams,
    RequestParamsMeta,
)
from mcp_types import methods as _methods
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar

from mcp.server.caching import apply_cache_hint
from mcp.server.connection import Connection
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import DispatchContext, Dispatcher, OnNotify, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

__all__ = [
    "CallNext",
    "ServerMiddleware",
    "ServerRunner",
    "aclose_shielded",
    "modern_on_request",
    "serve_connection",
    "serve_loop",
    "serve_one",
]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)


_INIT_EXEMPT: frozenset[str] = frozenset({"ping"})

_EXIT_STACK_CLOSE_TIMEOUT: float = 5
"""Bound for `aclose_shielded`; a hung cleanup callback must not wedge shutdown."""


def _extract_meta(params: Mapping[str, Any] | None) -> RequestParamsMeta | None:
    """Lift `_meta` from raw params; `None` when absent or malformed, so context construction never fails."""
    if not params or "_meta" not in params:
        return None
    try:
        return RequestParams.model_validate(params, by_name=False).meta
    except ValidationError:
        return None


def _dump_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, ErrorData):
        # Handler returns already raise in `_inner`; this catches middleware returning an ErrorData.
        raise MCPError.from_error_data(result)
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    if isinstance(result, dict):
        return cast(dict[str, Any], result)
    raise TypeError(f"handler returned {type(result).__name__}; expected BaseModel, dict, or None")


async def aclose_shielded(connection: Connection) -> None:
    """Unwind `connection.exit_stack` under a shielded, bounded scope.

    For driver `finally` blocks: cleanup runs even under cancellation, a hung callback cannot
    wedge shutdown, and a raising callback is logged so it never masks the driver's own exception.
    """
    with anyio.move_on_after(_EXIT_STACK_CLOSE_TIMEOUT, shield=True) as scope:
        try:
            await connection.exit_stack.aclose()
        except Exception:
            logger.exception("connection exit_stack cleanup raised")
    if scope.cancelled_caught:
        logger.warning(
            "connection exit_stack cleanup exceeded %s seconds; abandoning remaining callbacks",
            _EXIT_STACK_CLOSE_TIMEOUT,
        )


def _apply_middleware(
    middleware: ServerMiddleware[Any], call_next: CallNext, ctx: ServerRequestContext[Any, Any]
) -> Awaitable[HandlerResult]:
    """Bind `call_next`; take `ctx` at call time so a rewritten context flows down the chain."""
    return middleware(ctx, call_next)


@dataclass
class ServerRunner(Generic[LifespanT]):
    """Per-connection handler kernel. One instance per client connection."""

    server: Server[LifespanT]
    connection: Connection
    lifespan_state: LifespanT
    _: KW_ONLY
    init_options: InitializationOptions | None = None
    """`InitializeResult` payload. Defaults to `server.create_initialization_options()`."""

    @cached_property
    def on_request(self) -> OnRequest:
        return self._on_request

    @cached_property
    def on_notify(self) -> OnNotify:
        return self._on_notify

    async def _on_request(
        self,
        dctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        meta = _extract_meta(params)
        version = self.connection.protocol_version
        ctx = self._make_context(dctx, method, params, meta, version)

        async def _inner(ctx: ServerRequestContext[LifespanT, Any]) -> HandlerResult:
            # Read off `ctx` so a middleware rewrite via `call_next(replace(ctx, ...))` takes effect.
            method, params = ctx.method, ctx.params
            # Pinned compat: spec methods are surface-validated before lookup, so malformed params
            # are INVALID_PARAMS even with no handler; custom methods fall through to `entry.params_type`.
            if method in _methods.SPEC_CLIENT_METHODS:
                try:
                    _methods.validate_client_request(method, version, params)
                except KeyError:
                    raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method) from None
            # TODO(L29): the 2026-07-28 spec drops the handshake, making this branch and the gate a
            # per-version legacy path. Initialize runs inline (read loop parked); awaiting the peer here deadlocks.
            if method == "initialize":
                return self._serialize(method, version, self._handle_initialize(params))
            # No handler is METHOD_NOT_FOUND regardless of init state: JSON-RPC 2.0 reserves -32601 and
            # pre-handshake probes key off it, so the init gate below only applies to served methods.
            entry = self.server.get_request_handler(method)
            if entry is None:
                raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method)
            if not self.connection.initialize_accepted and method not in _INIT_EXEMPT:
                # Pinned compat: the same error shape the union validation produced.
                raise MCPError(code=INVALID_PARAMS, message="Invalid request parameters", data="")
            # Absent params validate as {} (required fields still reject): the handler gets defaults, never None.
            typed_params = entry.params_type.model_validate({} if params is None else params, by_name=False)
            result = await entry.handler(ctx, typed_params)
            if isinstance(result, ErrorData):
                # Raise inside the chain so middleware observes the failure.
                raise MCPError.from_error_data(result)
            # Fill cache hints before the serialize sieve drops version-absent fields; `input_required`
            # interim results are not `CacheableResult`, so the MRTR carve-out (no hints) holds by shape.
            if isinstance(result, CacheableResult) and (hint := self.server.cache_hints.get(method)) is not None:
                result = apply_cache_hint(result, hint)
            return self._serialize(method, version, result)

        call = self._compose_server_middleware(_inner)
        # `_inner` already produced the wire dict; a middleware that short-circuited without
        # `call_next` is trusted to return its own well-formed result.
        result = _dump_result(await call(ctx))
        if method == "initialize":
            # Commit only on chain success, so a middleware veto leaves no state. Race-free: the
            # read loop is parked until this call returns.
            # TODO: re-reads the wire `params`, so a middleware that rewrote `ctx.params`/`ctx.method` or
            # short-circuited can desync `connection.protocol_version` from the `InitializeResult`;
            # resolve when `initialize` becomes a built-in handler.
            self.connection.client_params, self.connection.protocol_version = self._negotiate_initialize(params)
        return result

    async def _on_notify(
        self,
        dctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> None:
        meta = _extract_meta(params)
        version = self.connection.protocol_version
        ctx = self._make_context(dctx, method, params, meta, version)

        async def _inner(ctx: ServerRequestContext[LifespanT, Any]) -> None:
            method, params = ctx.method, ctx.params
            if method in _methods.SPEC_CLIENT_NOTIFICATION_METHODS:
                try:
                    _methods.validate_client_notification(method, version, params)
                except KeyError:
                    logger.debug("dropped %r: not defined at %s", method, version)
                    return
                except ValidationError:
                    logger.warning("dropped %r: malformed params", method)
                    return
            if method == "notifications/initialized":
                # Surface validation above already rejected a malformed body, so commit; fall
                # through so a registered handler observes an initialized connection.
                self.connection.initialized.set()
            elif not self.connection.initialize_accepted:
                logger.debug("dropped %s: received before initialization", method)
                return
            entry = self.server.get_notification_handler(method)
            if entry is None:
                logger.debug("no handler for notification %s", method)
                return
            # Same absent-params contract as requests.
            try:
                typed_params = entry.params_type.model_validate({} if params is None else params, by_name=False)
            except ValidationError:
                logger.warning("dropped %r: malformed params", method)
                return
            await entry.handler(ctx, typed_params)

        call = self._compose_server_middleware(_inner)
        try:
            await call(ctx)
        except Exception:
            # A crashing handler must not cancel the dispatcher's task group; middleware saw the raise first.
            logger.exception("notification handler for %r raised", method)

    def _compose_server_middleware(self, inner: CallNext) -> CallNext:
        """Wrap `inner` in `Server.middleware`, outermost-first; one shared chain sees every inbound message."""
        call = inner
        for middleware in reversed(self.server.middleware):
            call = partial(_apply_middleware, middleware, call)
        return call

    def _make_context(
        self,
        dctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
        meta: RequestParamsMeta | None,
        protocol_version: str,
    ) -> ServerRequestContext[LifespanT, Any]:
        # TODO(L54): reads SHTTP per-request data off the raw `dctx.message_metadata` carrier;
        # replace with the per-transport context once the Context rework lands.
        md = dctx.message_metadata
        if isinstance(md, ServerMessageMetadata):
            request = md.request_context
            close_sse_stream = md.close_sse_stream
            close_standalone_sse_stream = md.close_standalone_sse_stream
        else:
            request = close_sse_stream = close_standalone_sse_stream = None
        # Per-request session: `dctx` is the request-scoped channel (auto-threads its request_id on
        # streamable HTTP); the standalone channel comes off `connection.outbound`. `related_request_id`
        # on the public API selects between them.
        session = ServerSession(dctx, self.connection)
        return ServerRequestContext(
            session=session,
            lifespan_context=self.lifespan_state,
            method=method,
            params=params,
            request_id=dctx.request_id,
            meta=meta,
            protocol_version=protocol_version,
            request=request,
            close_sse_stream=close_sse_stream,
            close_standalone_sse_stream=close_standalone_sse_stream,
        )

    @staticmethod
    def _serialize(method: str, version: str, result: HandlerResult) -> dict[str, Any]:
        """Dump a handler result to the wire dict, serializing spec methods.

        Runs inside the middleware chain so the OpenTelemetry span observes a failing return shape as an error.
        """
        dumped = _dump_result(result)
        # TODO(L56): reject resultType values outside {"complete", "input_required"} unless the
        # corresponding extension is in this request's _meta clientCapabilities.extensions; the
        # explicit MUST-reject is client-side (basic/index.mdx ResultType), this enforces it proactively.
        if method not in _methods.SPEC_CLIENT_METHODS:
            return dumped
        try:
            return _methods.serialize_server_result(method, version, dumped)
        except ValidationError:
            # Server bug, not client fault; pydantic detail (echoes the result body) stays in the log.
            logger.exception("handler for %r returned an invalid result", method)
            raise MCPError(code=INTERNAL_ERROR, message="Handler returned an invalid result") from None

    @staticmethod
    def _negotiate_initialize(params: Mapping[str, Any] | None) -> tuple[InitializeRequestParams, str]:
        """Validate `initialize` params and pick the protocol version."""
        init = InitializeRequestParams.model_validate(params or {}, by_name=False)
        requested = init.protocol_version
        negotiated = requested if requested in HANDSHAKE_PROTOCOL_VERSIONS else LATEST_HANDSHAKE_VERSION
        return init, negotiated

    def _handle_initialize(self, params: Mapping[str, Any] | None) -> InitializeResult:
        """Build the `initialize` result; state commits later in `_on_request`."""
        _, negotiated = self._negotiate_initialize(params)
        opts = self.init_options if self.init_options is not None else self.server.create_initialization_options()
        return InitializeResult(
            protocol_version=negotiated,
            capabilities=opts.capabilities,
            server_info=Implementation(
                name=opts.server_name,
                title=opts.title,
                description=opts.description,
                version=opts.server_version,
                website_url=opts.website_url,
                icons=opts.icons,
            ),
            instructions=opts.instructions,
        )


async def serve_connection(
    server: Server[LifespanT],
    dispatcher: Dispatcher[Any],
    *,
    connection: Connection,
    lifespan_state: LifespanT,
    init_options: InitializationOptions | None = None,
    task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
) -> None:
    """Drive `dispatcher` until the underlying channel closes.

    The loop-mode driver: tears down `connection.exit_stack` (shielded) on the way out.
    The entry constructs the `Connection`; this only consumes it.
    """
    runner = ServerRunner(server, connection, lifespan_state, init_options=init_options)
    try:
        await dispatcher.run(runner.on_request, runner.on_notify, task_status=task_status)
    finally:
        await aclose_shielded(connection)


async def serve_loop(
    server: Server[LifespanT],
    read_stream: ReadStream[SessionMessage | Exception],
    write_stream: WriteStream[SessionMessage],
    *,
    lifespan_state: LifespanT,
    session_id: str | None = None,
    init_options: InitializationOptions | None = None,
    raise_exceptions: bool = False,
) -> None:
    """Drive `server` in loop mode over a stream pair until the channel closes.

    Builds the loop-mode `JSONRPCDispatcher` + `Connection` for `serve_connection` so loop-mode
    callers share one dispatcher-construction recipe. Callers owning a lifespan (the
    streamable-HTTP manager) pass its state in; `Server.run` (stdio/memory) enters the lifespan first.
    """
    dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        read_stream,
        write_stream,
        raise_handler_exceptions=raise_exceptions,
        # Handle `initialize` inline so a client that pipelines it with the next request
        # (spec: SHOULD NOT, not MUST NOT) sees initialized state instead of failing the gate.
        inline_methods=frozenset({"initialize"}),
    )
    connection = Connection.for_loop(dispatcher, session_id=session_id)
    await serve_connection(
        server, dispatcher, connection=connection, lifespan_state=lifespan_state, init_options=init_options
    )


async def serve_one(
    server: Server[LifespanT],
    dctx: DispatchContext[TransportContext],
    method: str,
    params: Mapping[str, Any] | None,
    *,
    connection: Connection,
    lifespan_state: LifespanT,
) -> dict[str, Any]:
    """Handle a single request `(method, params)` and return its result dict.

    The single-exchange driver: tears down `connection.exit_stack` (shielded) on the way out.
    The entry constructs the (born-ready) `Connection` and `dctx`; this only consumes them.

    Raises whatever the handler chain raises; callers own the exception-to-wire mapping.
    """
    runner = ServerRunner(server, connection, lifespan_state)
    try:
        return await runner.on_request(dctx, method, params)
    finally:
        await aclose_shielded(connection)


def modern_on_request(server: Server[LifespanT], lifespan_state: LifespanT) -> OnRequest:
    """Return an `OnRequest` callback that serves each call via `serve_one` with a fresh per-request `Connection`.

    For the server side of a `DirectDispatcher` peer-pair on the modern per-request-envelope
    path (protocol version, client info, and capabilities ride in `params._meta`; no
    `initialize` handshake). Like `serve_one`, raises whatever the handler chain raises.
    """

    async def handle(
        dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        meta = (params or {}).get("_meta", {})
        connection = Connection.from_envelope(
            meta.get(PROTOCOL_VERSION_META_KEY, LATEST_MODERN_VERSION),
            meta.get(CLIENT_INFO_META_KEY),
            meta.get(CLIENT_CAPABILITIES_META_KEY),
        )
        return await serve_one(server, dctx, method, params, connection=connection, lifespan_state=lifespan_state)

    return handle
