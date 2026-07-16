"""`ServerRunner` - the per-connection handler kernel.

`ServerRunner` bridges the dispatch layer (`on_request` / `on_notify`, untyped
dicts) and the user's handler layer (typed `Context`, typed params). It is a
pure kernel: it holds a pre-populated `Connection` and reads
`connection.protocol_version` / `connection.outbound` as facts. Driving a
dispatcher loop and tearing down the connection live in the free-function
drivers (`serve_connection`, `serve_loop`, `serve_dual_era_loop`, `serve_one`);
the entry constructs the `Connection`, the driver tears it down.

`ServerRunner` holds a `Server` directly - `Server` is the registry.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Mapping
from dataclasses import KW_ONLY, dataclass
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any, Generic, Literal, cast

import anyio
import anyio.abc
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    CacheableResult,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    RequestParams,
    RequestParamsMeta,
    UnsupportedProtocolVersionErrorData,
)
from mcp_types import methods as _methods
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    LATEST_MODERN_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar

from mcp.server.caching import apply_cache_hint
from mcp.server.connection import Connection, NotifyOnlyOutbound
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import (
    DispatchContext,
    Dispatcher,
    NoServerRequestsDispatchContext,
    OnNotify,
    OnRequest,
)
from mcp.shared.exceptions import MCPError
from mcp.shared.inbound import InboundLadderRejection, classify_inbound_request
from mcp.shared.jsonrpc_dispatcher import (
    JSONRPCDispatcher,
    handler_exception_to_error_data,
    observe_success_frames,
    suppress_cancel_answer,
)
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
    "serve_dual_era_loop",
    "serve_loop",
    "serve_one",
]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)


_INIT_EXEMPT: frozenset[str] = frozenset({"ping"})

_EXIT_STACK_CLOSE_TIMEOUT: float = 5
"""Bound for `aclose_shielded`'s exit-stack unwind; a hung cleanup callback
must not wedge shutdown."""


def _extract_meta(params: Mapping[str, Any] | None) -> RequestParamsMeta | None:
    """Lift `_meta` from raw params; `None` when absent or malformed, so
    context construction is independent of params validity."""
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
        # ErrorData is a JSON-RPC error, not a success result. Handler returns
        # already raise in `_inner`; this catches middleware returning one.
        raise MCPError.from_error_data(result)
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    if isinstance(result, dict):
        return cast(dict[str, Any], result)
    raise TypeError(f"handler returned {type(result).__name__}; expected BaseModel, dict, or None")


async def aclose_shielded(connection: Connection) -> None:
    """Unwind ``connection.exit_stack`` under a shielded, bounded scope.

    Called from a driver's ``finally``: the shield lets per-connection cleanup
    callbacks run even when the driver itself is being cancelled, the
    `_EXIT_STACK_CLOSE_TIMEOUT` bound stops a hung callback wedging shutdown,
    and a raising callback is logged-and-swallowed so it never masks the
    driver's own exception.
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
    """Adapt one middleware to the `CallNext` shape: bind `call_next`, take
    `ctx` at call time so a rewritten context flows down the chain."""
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
            # Read method/params off `ctx` so a middleware that rewrote them via
            # `call_next(replace(ctx, ...))` reaches lookup and the handler.
            method, params = ctx.method, ctx.params
            # Pinned compat: spec methods are surface-validated before lookup,
            # so malformed params are INVALID_PARAMS even with no handler
            # registered. Custom methods miss the monolith map and fall through
            # to `entry.params_type` exactly as before.
            if method in _methods.SPEC_CLIENT_METHODS:
                try:
                    _methods.validate_client_request(method, version, params)
                except KeyError:
                    raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method) from None
            # TODO(L29): the 2026-07-28 spec drops the handshake; this branch and
            # the gate become a per-version legacy path then. Initialize runs inline
            # (read loop parked), so awaiting the peer anywhere on this path deadlocks.
            if method == "initialize":
                return self._serialize(method, version, self._handle_initialize(params))
            # Methods without a handler are METHOD_NOT_FOUND regardless of
            # initialization state: JSON-RPC 2.0 reserves -32601 for "not
            # available on this server", and clients probing a server before
            # the handshake key off that code. The init gate below therefore
            # only ever applies to methods the server actually serves.
            entry = self.server.get_request_handler(method)
            if entry is None:
                raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method)
            if not self.connection.initialize_accepted and method not in _INIT_EXEMPT:
                # Pinned compat: the same error shape the union validation produced.
                raise MCPError(code=INVALID_PARAMS, message="Invalid request parameters", data="")
            # Absent params validate as {} (required fields still reject), so
            # the handler receives the model with its defaults, never None.
            typed_params = entry.params_type.model_validate({} if params is None else params, by_name=False)
            result = await entry.handler(ctx, typed_params)
            if isinstance(result, ErrorData):
                # Raise inside the chain so middleware observes the failure.
                raise MCPError.from_error_data(result)
            # Fill cache hints on the handler result, before the serialize sieve
            # decides whether the negotiated version carries the fields at all.
            # MRTR carve-out: `input_required` interim results, typed or mapping, never get hints.
            if (hint := self.server.cache_hints.get(method)) is not None:
                if isinstance(result, CacheableResult):
                    result = apply_cache_hint(result, hint)
                elif isinstance(result, Mapping) and not _methods.is_input_required(result):
                    # Hint keys first so wire keys the handler set win, matching `apply_cache_hint` precedence.
                    result = {"ttlMs": hint.ttl_ms, "cacheScope": hint.scope, **result}
            # Dump and serialize inside the chain so the OpenTelemetry span (the
            # outermost middleware) records a failing handler return shape too.
            return self._serialize(method, version, result)

        call = self._compose_server_middleware(_inner)
        # `_inner` already produced the wire dict; a middleware that short-circuited
        # without `call_next` is trusted to return its own well-formed result.
        result = _dump_result(await call(ctx))
        if method == "initialize":
            # Commit only on chain success, so a middleware veto leaves no state.
            # Race-free: the read loop is parked until this call returns.
            # TODO: this re-reads the wire `params`, so a middleware that rewrote
            # `ctx.params` (or `ctx.method`, or short-circuited without `call_next`)
            # can leave `connection.protocol_version` out of step with the
            # `InitializeResult` `_inner` produced. Resolve when `initialize` becomes
            # a built-in handler so commit and result derive from one negotiation.
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
                # Surface validation above already rejected a malformed body, so
                # commit; fall through so a registered handler observes an
                # initialized connection.
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
            # A crashing handler must not cancel the dispatcher's task group;
            # middleware saw the raise out of call_next() first.
            logger.exception("notification handler for %r raised", method)

    def _compose_server_middleware(self, inner: CallNext) -> CallNext:
        """Wrap `inner` in `Server.middleware`, outermost-first.

        Shared by `_on_request` and `_on_notify` so the same middleware chain
        observes every inbound message. The composed callable takes the `ctx`
        at call time, so a middleware can rewrite it for the rest of the chain.
        """
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
        # TODO(L54): remove for Context rework. Reads the SHTTP per-request
        # data off the raw `dctx.message_metadata` carrier; replace with the
        # per-transport context once that lands.
        md = dctx.message_metadata
        if isinstance(md, ServerMessageMetadata):
            request = md.request_context
            close_sse_stream = md.close_sse_stream
            close_standalone_sse_stream = md.close_standalone_sse_stream
        else:
            request = close_sse_stream = close_standalone_sse_stream = None
        # Per-request session: `dctx` is the request-scoped channel (auto-threads
        # its own request_id on streamable HTTP); the standalone channel is read
        # off `connection.outbound`. `related_request_id` on the public API selects.
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

        Runs inside the middleware chain so the OpenTelemetry span observes a
        failing return shape (unsupported type, malformed spec result) as an
        error rather than closing on a request that the client sees fail.
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
            # Server bug, not client fault. Detail stays in the server log:
            # pydantic messages echo the result body.
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
    """Drive ``dispatcher`` until the underlying channel closes.

    The loop-mode driver: builds the kernel, hands `on_request`/`on_notify`
    to `dispatcher.run()`, and tears down `connection.exit_stack` (shielded)
    on the way out. The entry constructs the `Connection`; this only consumes
    it.
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
    """Drive ``server`` in handshake-only loop mode over a stream pair until the channel closes.

    Builds the loop-mode `JSONRPCDispatcher` + `Connection` and hands them to
    `serve_connection`. The streamable-HTTP manager (which owns its lifespan
    and serves the modern era on the single-exchange entry instead) calls
    this; `Server.run` drives `serve_dual_era_loop`, which extends the same
    dispatcher recipe (notably the `inline_methods={"initialize"}` rule) with
    era routing.
    """
    dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        read_stream,
        write_stream,
        raise_handler_exceptions=raise_exceptions,
        # Handle `initialize` inline so a client that pipelines it with the
        # next request (spec: SHOULD NOT, not MUST NOT) sees the initialized
        # state instead of failing the init-gate.
        inline_methods=frozenset({"initialize"}),
    )
    connection = Connection.for_loop(dispatcher, session_id=session_id)
    await serve_connection(
        server, dispatcher, connection=connection, lifespan_state=lifespan_state, init_options=init_options
    )


_MODERN_ENVELOPE_KEYS = (PROTOCOL_VERSION_META_KEY, CLIENT_INFO_META_KEY, CLIENT_CAPABILITIES_META_KEY)


def _has_modern_envelope(params: Mapping[str, Any] | None) -> bool:
    """Whether `params._meta` carries every reserved modern-envelope key.

    Era evidence is the FULL key triple - bare `_meta` is not (legacy traffic
    carries `progressToken` there).
    """
    if not params:
        return False
    meta = params.get("_meta")
    return isinstance(meta, Mapping) and all(key in meta for key in _MODERN_ENVELOPE_KEYS)


def _initialize_after_modern_data(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Error data for an `initialize` arriving on a modern-locked connection.

    The typed -32022 payload when the client's proposed version is parseable;
    otherwise just the supported list (the point is naming what we serve).
    """
    requested = (params or {}).get("protocolVersion")
    if isinstance(requested, str):
        return UnsupportedProtocolVersionErrorData(
            supported=list(MODERN_PROTOCOL_VERSIONS), requested=requested
        ).model_dump(mode="json")
    return {"supported": list(MODERN_PROTOCOL_VERSIONS)}


def modern_error_data(exc: Exception) -> ErrorData:
    """Map a modern request's handler exception to its wire `ErrorData`.

    The exception-to-wire fact shared by the modern entries (the
    single-exchange HTTP path and the dual-era stream loop), so an identical
    modern request fails identically on every transport: `MCPError` and
    `ValidationError` map via the shared `handler_exception_to_error_data`
    ladder; anything else is logged server-side and surfaced as a generic
    INTERNAL_ERROR so handler internals never reach the wire.
    """
    error = handler_exception_to_error_data(exc)
    if error is not None:
        return error
    logger.exception("modern request handler raised")
    return ErrorData(code=INTERNAL_ERROR, message="Internal server error")


async def serve_dual_era_loop(
    server: Server[LifespanT],
    read_stream: ReadStream[SessionMessage | Exception],
    write_stream: WriteStream[SessionMessage],
    *,
    lifespan_state: LifespanT,
    session_id: str | None = None,
    init_options: InitializationOptions | None = None,
    raise_exceptions: bool = False,
) -> None:
    """Drive `server` over a duplex stream pair, serving both protocol eras.

    The stream-pair counterpart of the modern HTTP entry's era router. Era is
    a property of the connection, decided by how the client opens it, and
    mid-stream switching is undefined - so the first era-distinctive message
    to SUCCEED locks the connection (matching the typescript-sdk):

    - A successful `initialize` locks legacy: the connection behaves exactly
      like `serve_loop` for its lifetime, and modern envelope traffic is then
      rejected with INVALID_REQUEST. `initialize` never routes modern - the
      method is legacy-distinctive by definition - even when a confused
      client stamps the envelope triple on it.
    - A request carrying the modern `_meta` envelope triple - or
      `server/discover`, a modern-only method - is classified
      (`classify_inbound_request`) and served single-exchange via `serve_one`
      with a born-ready per-request `Connection`, the same dispatch model as
      the modern HTTP entry. The first such request to succeed locks the
      connection modern; a later `initialize` is then rejected with
      UNSUPPORTED_PROTOCOL_VERSION naming the modern versions.

    Modern connections push notifications over the duplex pipe but refuse
    server-initiated requests on both channels (the modern protocol forbids
    them). A request that fails - rejected classification, malformed envelope
    content, unknown method - never locks either era, so a failed probe
    leaves the legacy handshake available: released auto-negotiating clients
    fall back on any error code except -32022, and that code is only emitted
    for genuine version negotiation or for `initialize` on an
    already-modern connection.

    The modern lock commits on the FIRST client-visible success frame the
    classified request produces - a request-scoped notification (progress and
    the `subscriptions/listen` ack ride those) or its result - immediately
    before that frame is written, with no checkpoint in between. One
    definition for every method: a plain request locks at its response
    exactly as before, and a streaming request (`subscriptions/listen`, whose
    response arrives only at close) locks at its ack, so a pipelined
    `initialize` behind the ack can never hijack a live stream back to
    legacy. For the inline methods (`initialize`, `server/discover`) the
    dispatch completes before the next frame is read, so the canonical
    probe-then-go flow is race-free; a pinned-modern client that pipelines
    frames ahead of its first response should expect envelope-less
    notifications sent in that window to be dropped. The lock settles exactly
    once: a request from the other era that was already in flight when the
    lock committed may still complete and its response stands, but the era
    does not move; and a peer cancel observed before the first frame's write
    begins prevents the lock (the commit re-checks `cancel_requested` at fire
    time).

    One residual corner is accepted, deliberately: the lock commits
    immediately before the frame's transport write, and that write's own
    checkpoint is the first point a pending peer cancel can land - so a
    cancel arriving DURING the write cancels the frame away after the lock
    already committed, leaving the connection locked modern with ZERO frames
    delivered. Only mid-handler frames (the listen ack, progress) have this
    window; a plain request's response cannot be cancelled away (its
    in-flight entry is removed before the response write starts, with no
    checkpoint in between, so a peer cancel no longer reaches it). The
    converse exists too: a handler that shields its own send past a pending
    cancel delivers a frame WITHOUT the lock - `era_settles` declined at fire
    time - but that frame is output the handler forced after the cancel said
    stop, not a state this loop produces. The
    orphaned lock is self-consistent and client-recoverable: only a
    validly-classified modern envelope reaches this path, so the peer already
    committed to modern; a follow-up `initialize` is answered with
    UNSUPPORTED_PROTOCOL_VERSION (-32022) naming the modern versions, which
    released auto-negotiating clients treat as modern evidence and re-probe;
    and the connection keeps serving modern traffic. Closing the corner would
    require committing the lock only after the write is known delivered,
    which reopens the worse race this design exists to prevent (an
    `initialize` pipelined behind an ack the client already read, flipping a
    live stream legacy).

    Classified-modern requests are also governed by the 2026 cancellation
    rule for their whole lifetime: after an inbound `notifications/cancelled`
    the server sends nothing further for that request - no result, no error
    (the transport spec's MUST NOT). Once the connection is LOCKED modern the
    rule widens from classification-scoped to connection-scoped: every
    request - including one rejected before classification succeeds
    (envelope-less, malformed envelope) - carries the silence commitment, so
    a rejection error computed after the peer's cancel never reaches the wire
    (the rejection itself, absent a cancel, is of course still answered).
    Legacy-era requests keep the byte-identical "Request cancelled" answer
    released 2025 clients expect - including a legacy-classified request
    still in flight when the modern lock commits (the straggler carve-out
    covers its cancel answer, not just its response) - as does a request that
    fails classification on a still-unlocked connection: an unclassifiable
    request has not proven modern semantics, so the legacy answer stands
    there.
    """
    dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
        read_stream,
        write_stream,
        raise_handler_exceptions=raise_exceptions,
        # `initialize` inline for the same pipelining reason as `serve_loop`;
        # `server/discover` inline so the modern era lock commits before the
        # next pipelined message is read.
        inline_methods=frozenset({"initialize", "server/discover"}),
    )
    loop_connection = Connection.for_loop(dispatcher, session_id=session_id)
    loop_runner = ServerRunner(server, loop_connection, lifespan_state, init_options=init_options)
    standalone_outbound = NotifyOnlyOutbound(dispatcher)
    era: Literal["unlocked", "legacy", "modern"] = "unlocked"
    modern_version = LATEST_MODERN_VERSION

    def era_settles(dctx: DispatchContext[TransportContext]) -> bool:
        # The one definition of "this request may lock the era": it produced
        # a client-visible success on a still-unlocked connection. The lock is
        # monotone - the first success wins, so a straggling request from the
        # other era can never overwrite a committed lock. A pending peer
        # cancel means the client already abandoned this request and will
        # never read the frame as a success: no lock.
        return era == "unlocked" and not dctx.cancel_requested.is_set()

    def commit_modern(dctx: DispatchContext[TransportContext], version: str) -> None:
        # The success-frame observer for classified-modern requests: invoked
        # immediately before each non-error frame's write, with no checkpoint
        # in between - by the time the client can read any modern output, the
        # era is locked and a pipelined `initialize` is rejected instead of
        # hijacking the connection. `era_settles` re-checks `cancel_requested`
        # at fire time; the cancel-during-the-write residue is the accepted
        # corner documented on `serve_dual_era_loop`.
        nonlocal era, modern_version
        if era_settles(dctx):
            era, modern_version = "modern", version

    async def serve_modern(
        dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        route = classify_inbound_request({"method": method, "params": params})
        if isinstance(route, InboundLadderRejection):
            raise MCPError(code=route.code, message=route.message, data=route.data)
        # Classification succeeded: 2026 wire semantics govern this request's
        # lifecycle from here. On a still-unlocked connection this is the
        # silence rule's exact scope - a request that fails classification
        # above has not proven modern semantics and keeps the legacy cancel
        # answer - and the era lock rides the request's first success frame.
        # Both facts attach synchronously - no checkpoint since the
        # dispatcher entered the handler scope - so a peer cancel can never
        # interleave and observe the legacy defaults. Once the connection is
        # locked, neither attaches here: `on_request` owns the
        # connection-scoped silence fact, and the lock can never move again.
        if era == "unlocked":
            suppress_cancel_answer(dctx)
            observe_success_frames(dctx, partial(commit_modern, dctx, route.protocol_version))
        connection = Connection.from_envelope(
            route.protocol_version,
            route.client_info,
            route.client_capabilities,
            outbound=standalone_outbound,
        )
        try:
            return await serve_one(
                server,
                NoServerRequestsDispatchContext(dctx),
                method,
                params,
                connection=connection,
                lifespan_state=lifespan_state,
            )
        except (MCPError, ValidationError):
            # The dispatcher's shared ladder maps these to the same wire error
            # the modern HTTP entry produces.
            raise
        except Exception as exc:
            if raise_exceptions:
                raise
            error = modern_error_data(exc)
            raise MCPError(code=error.code, message=error.message, data=error.data) from exc

    async def on_request(
        dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        nonlocal era
        if era == "legacy":
            if _has_modern_envelope(params):
                raise MCPError(
                    code=INVALID_REQUEST,
                    message="connection is locked to the legacy handshake era; "
                    "modern envelope requests are not accepted",
                )
            # Bare modern-only methods (e.g. `server/discover`) fall through to
            # the loop runner's per-version surface validation - the same
            # METHOD_NOT_FOUND a handshake-only server produced, byte for byte.
            return await loop_runner.on_request(dctx, method, params)
        if era == "modern":
            # Connection-scoped silence: once locked modern, EVERY request is
            # governed by the 2026 cancellation rule, rejections included - a
            # rejection error is a legitimate answer, but nothing may follow
            # the peer's `notifications/cancelled`. Pre-classification rejects
            # run on a spawned task, so an adjacent cancel can precede them
            # under trio's randomized scheduling (asyncio's FIFO always starts
            # the reject's answer write first - the legitimate
            # already-answering case; inline `initialize` has no window at
            # all). See the cancellation paragraph on `serve_dual_era_loop`.
            suppress_cancel_answer(dctx)
            if method == "initialize":
                raise MCPError(
                    code=UNSUPPORTED_PROTOCOL_VERSION,
                    message="connection already negotiated a modern protocol version",
                    data=_initialize_after_modern_data(params),
                )
            return await serve_modern(dctx, method, params)
        # Unlocked. `initialize` is legacy-distinctive by definition (the
        # method does not exist at modern versions), so it takes the handshake
        # path even when the envelope triple is stamped on it.
        if method != "initialize" and (method == "server/discover" or _has_modern_envelope(params)):
            return await serve_modern(dctx, method, params)
        result = await loop_runner.on_request(dctx, method, params)
        if method == "initialize" and era_settles(dctx):
            # Lock only on success: a failed handshake leaves both eras open.
            era = "legacy"
        return result

    async def on_notify(dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        if era != "modern":
            return await loop_runner.on_notify(dctx, method, params)
        # The envelope is request-only, so notifications inherit the
        # connection's locked version.
        connection = Connection.from_envelope(modern_version, None, None, outbound=standalone_outbound)
        notify_runner = ServerRunner(server, connection, lifespan_state)
        try:
            await notify_runner.on_notify(NoServerRequestsDispatchContext(dctx), method, params)
        finally:
            await aclose_shielded(connection)

    try:
        await dispatcher.run(on_request, on_notify)
    finally:
        await aclose_shielded(loop_connection)


async def serve_one(
    server: Server[LifespanT],
    dctx: DispatchContext[TransportContext],
    method: str,
    params: Mapping[str, Any] | None,
    *,
    connection: Connection,
    lifespan_state: LifespanT,
) -> dict[str, Any]:
    """Handle a single request ``(method, params)`` and return its result dict.

    The single-exchange driver: builds the kernel, runs `on_request` once under
    `dctx`, and tears down `connection.exit_stack` (shielded) on the way out.
    The entry constructs the (born-ready) `Connection` and the `dctx`; this
    only consumes them.

    Raises whatever the handler chain raises (`MCPError` / `ValidationError` /
    unmapped); callers own the exception-to-wire mapping.
    """
    runner = ServerRunner(server, connection, lifespan_state)
    try:
        return await runner.on_request(dctx, method, params)
    finally:
        await aclose_shielded(connection)


def modern_on_request(server: Server[LifespanT], lifespan_state: LifespanT) -> OnRequest:
    """Return an `OnRequest` callback that serves each call via `serve_one` with a fresh per-request `Connection`.

    Wire this into the server side of a `DirectDispatcher` peer-pair to drive an
    in-process server on the modern per-request-envelope path (each request
    carries protocol version, client info, and capabilities in `params._meta`;
    no `initialize` handshake). The dispatch context is wrapped in the
    server-requests denial, so the modern prohibition on server-initiated
    JSON-RPC requests holds on this entry like on the others. Like `serve_one`,
    this raises whatever the handler chain raises - the dispatcher owns the
    exception-to-error mapping.
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
        return await serve_one(
            server,
            NoServerRequestsDispatchContext(dctx),
            method,
            params,
            connection=connection,
            lifespan_state=lifespan_state,
        )

    return handle
