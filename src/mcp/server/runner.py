"""`ServerRunner` - the per-connection handler kernel.

`ServerRunner` bridges the dispatch layer (`on_request` / `on_notify`, untyped
dicts) and the user's handler layer (typed `Context`, typed params). It is a
pure kernel: it holds a pre-populated `Connection` and reads
`connection.protocol_version` / `connection.outbound` as facts. Driving a
dispatcher loop and tearing down the connection live in the free-function
drivers (`serve_connection`, `serve_loop`, `serve_one`); the entry constructs
the `Connection`, the driver tears it down.

`ServerRunner` holds a `Server` directly - `Server` is the registry.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from functools import cached_property, partial, reduce
from typing import TYPE_CHECKING, Any, Generic, cast

import anyio
import anyio.abc
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar

from mcp.server.connection import Connection
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._otel import extract_trace_context, otel_span
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import DispatchContext, Dispatcher, DispatchMiddleware, OnNotify, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher, handler_exception_to_error_data
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
    RequestParams,
    RequestParamsMeta,
)
from mcp.types import methods as _methods

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

__all__ = [
    "CallNext",
    "ServerMiddleware",
    "ServerRunner",
    "aclose_shielded",
    "otel_middleware",
    "serve_connection",
    "serve_loop",
    "serve_one",
    "to_jsonrpc_response",
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


def otel_middleware(next_on_request: OnRequest) -> OnRequest:
    """Dispatch-tier middleware that wraps each request in an OpenTelemetry span.

    Mirrors the span shape of the existing `Server._handle_request`: span name
    `"MCP handle <method> [<target>]"`, `mcp.method.name` attribute, W3C
    trace context extracted from `params._meta` (SEP-414), and an ERROR
    status if the handler raises.
    """

    async def wrapped(
        dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        target: str | None
        match params:
            case {"name": str() as target}:
                pass
            case _:
                target = None
        parent: Any | None
        match params:
            case {"_meta": {**meta}}:
                parent = extract_trace_context(meta)
            case _:
                parent = None
        span_name = f"MCP handle {method}{f' {target}' if target else ''}"
        # `otel_middleware` wraps `on_request` only, so `request_id` is always set.
        attributes = {"mcp.method.name": method, "jsonrpc.request.id": str(dctx.request_id)}
        with otel_span(
            span_name,
            kind=SpanKind.SERVER,
            attributes=attributes,
            context=parent,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                return await next_on_request(dctx, method, params)
            except MCPError as e:
                span.set_status(StatusCode.ERROR, e.error.message)
                raise
            except ValidationError:
                # Mirror the sanitized wire response; pydantic messages carry client input.
                span.set_status(StatusCode.ERROR, "Invalid request parameters")
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                raise

    return wrapped


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


async def to_jsonrpc_response(request_id: RequestId, coro: Awaitable[dict[str, Any]]) -> JSONRPCResponse | JSONRPCError:
    """Await ``coro`` and wrap its outcome as the JSON-RPC reply for ``request_id``.

    The exception-to-wire boundary for the request-per-call drivers
    (`serve_one`, the modern HTTP entry). `MCPError` and `ValidationError`
    map via the shared `handler_exception_to_error_data` ladder; any other
    exception is logged and surfaced as `INTERNAL_ERROR` so handler internals
    never reach the wire.
    """
    try:
        result = await coro
    except Exception as exc:
        error = handler_exception_to_error_data(exc)
        if error is None:
            logger.exception("request handler raised")
            error = ErrorData(code=INTERNAL_ERROR, message="Internal server error")
        return JSONRPCError(jsonrpc="2.0", id=request_id, error=error)
    return JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result)


@dataclass
class ServerRunner(Generic[LifespanT]):
    """Per-connection handler kernel. One instance per client connection."""

    server: Server[LifespanT]
    connection: Connection
    lifespan_state: LifespanT
    _: KW_ONLY
    init_options: InitializationOptions | None = None
    """`InitializeResult` payload. Defaults to `server.create_initialization_options()`."""
    dispatch_middleware: Sequence[DispatchMiddleware] = (otel_middleware,)

    @cached_property
    def on_request(self) -> OnRequest:
        """`_on_request` wrapped in `dispatch_middleware`, outermost-first.

        Dispatch-tier middleware sees raw `(dctx, method, params) -> dict` and
        wraps everything - initialize, METHOD_NOT_FOUND, validation failures
        included.
        """
        return reduce(lambda h, mw: mw(h), reversed(self.dispatch_middleware), self._on_request)

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
        ctx = self._make_context(dctx, meta, version)
        is_spec_method = method in _methods.SPEC_CLIENT_METHODS

        async def _inner() -> HandlerResult:
            # Pinned compat: spec methods are surface-validated before lookup,
            # so malformed params are INVALID_PARAMS even with no handler
            # registered. Custom methods miss the monolith map and fall through
            # to `entry.params_type` exactly as before.
            if is_spec_method:
                try:
                    _methods.validate_client_request(method, version, params)
                except KeyError:
                    raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method) from None
            # TODO(L29): the 2026-07-28 spec drops the handshake; this branch and
            # the gate become a per-version legacy path then. Initialize runs inline
            # (read loop parked), so awaiting the peer anywhere on this path deadlocks.
            if method == "initialize":
                if self.connection.client_params is not None:
                    raise MCPError(code=INVALID_REQUEST, message="Server is already initialized")
                return self._handle_initialize(params)
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
            return result

        call = self._compose_server_middleware(ctx, method, params, _inner)
        result = _dump_result(await call())
        # TODO(L56): reject resultType values outside {"complete", "input_required"} unless the
        # corresponding extension is in this request's _meta clientCapabilities.extensions; the
        # explicit MUST-reject is client-side (basic/index.mdx ResultType), this enforces it proactively.
        if is_spec_method:
            try:
                result = _methods.serialize_server_result(method, version, result)
            except KeyError:
                # Middleware short-circuited a wrong-version spec method without
                # calling `call_next`; it owns the result shape.
                pass
            except ValidationError:
                # Server bug, not client fault. Detail stays in the server log:
                # pydantic messages echo the result body.
                logger.exception("handler for %r returned an invalid result", method)
                raise MCPError(code=INTERNAL_ERROR, message="Handler returned an invalid result") from None
        if method == "initialize":
            # Commit only on chain success, so a middleware veto leaves no state.
            # Race-free: the read loop is parked until this call returns.
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
        ctx = self._make_context(dctx, meta, version)

        async def _inner() -> None:
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

        call = self._compose_server_middleware(ctx, method, params, _inner)
        try:
            await call()
        except Exception:
            # A crashing handler must not cancel the dispatcher's task group;
            # middleware saw the raise out of call_next() first.
            logger.exception("notification handler for %r raised", method)

    def _compose_server_middleware(
        self,
        ctx: ServerRequestContext[LifespanT, Any],
        method: str,
        params: Mapping[str, Any] | None,
        inner: CallNext,
    ) -> CallNext:
        """Wrap `inner` in `Server.middleware`, outermost-first.

        Shared by `_on_request` and `_on_notify` so the same middleware chain
        observes every inbound message.
        """
        call = inner
        for mw in reversed(self.server.middleware):
            call = partial(mw, ctx, method, params, call)
        return call

    def _make_context(
        self, dctx: DispatchContext[TransportContext], meta: RequestParamsMeta | None, protocol_version: str
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
            request_id=dctx.request_id,
            meta=meta,
            protocol_version=protocol_version,
            request=request,
            close_sse_stream=close_sse_stream,
            close_standalone_sse_stream=close_standalone_sse_stream,
        )

    @staticmethod
    def _negotiate_initialize(params: Mapping[str, Any] | None) -> tuple[InitializeRequestParams, str]:
        """Validate `initialize` params and pick the protocol version."""
        init = InitializeRequestParams.model_validate(params or {}, by_name=False)
        requested = init.protocol_version
        negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
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
    """Drive ``server`` in loop mode over a stream pair until the channel closes.

    Builds the loop-mode `JSONRPCDispatcher` + `Connection` and hands them to
    `serve_connection`, so loop-mode callers share one dispatcher-construction
    recipe (notably the `inline_methods={"initialize"}` rule). Callers that own
    a lifespan (the streamable-HTTP manager) pass it in; callers that don't
    (`Server.run` for stdio/memory) enter the lifespan and then call this.
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


async def serve_one(
    server: Server[LifespanT],
    request: JSONRPCRequest,
    *,
    connection: Connection,
    dctx: DispatchContext[TransportContext],
    lifespan_state: LifespanT,
) -> JSONRPCResponse | JSONRPCError:
    """Handle a single ``request`` and return its JSON-RPC reply.

    The single-exchange driver: builds the kernel, runs `on_request` once for
    `request` under `dctx`, maps the outcome to a `JSONRPCResponse` /
    `JSONRPCError` via `to_jsonrpc_response`, and tears down
    `connection.exit_stack` (shielded) on the way out. The entry constructs
    the (born-ready) `Connection` and the `dctx`; this only consumes them.
    """
    runner = ServerRunner(server, connection, lifespan_state)
    try:
        return await to_jsonrpc_response(request.id, runner.on_request(dctx, request.method, request.params))
    finally:
        await aclose_shielded(connection)
