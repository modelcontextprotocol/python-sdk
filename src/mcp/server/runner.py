"""`ServerRunner` - per-connection orchestrator over a `Dispatcher`.

`ServerRunner` is the bridge between the dispatcher layer (`on_request` /
`on_notify`, untyped dicts) and the user's handler layer (typed `Context`,
typed params). One instance per client connection. It:

* handles the `initialize` handshake and populates `Connection`
* gates requests until initialized (`ping` exempt)
* looks up the handler in the server's registry, validates params, builds
  `Context`, runs the middleware chain, returns the result dict
* drives `dispatcher.run()` and the per-connection lifespan

`ServerRunner` holds a `Server` directly - `Server` is the registry.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial, reduce
from typing import TYPE_CHECKING, Any, Generic, cast, get_args

import anyio.abc
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, ValidationError
from typing_extensions import TypeVar

from mcp.server.connection import Connection
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._otel import extract_trace_context, otel_span
from mcp.shared.dispatcher import DispatchContext, DispatchMiddleware, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.transport_context import TransportContext
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    ClientRequest,
    ErrorData,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    NotificationParams,
    RequestParams,
    RequestParamsMeta,
    client_request_adapter,
)

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

__all__ = ["CallNext", "ServerMiddleware", "ServerRunner", "otel_middleware"]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)


_INIT_EXEMPT: frozenset[str] = frozenset({"ping"})

_EXIT_STACK_CLOSE_TIMEOUT: float = 5
"""Bound for the shielded exit-stack unwind in `run()`; a hung cleanup
callback must not wedge shutdown."""


def _extract_meta(params: Mapping[str, Any] | None) -> RequestParamsMeta | None:
    """Lift `_meta` from raw params; `None` when absent or malformed, so
    context construction is independent of params validity."""
    if not params or "_meta" not in params:
        return None
    try:
        return RequestParams.model_validate(params, by_name=False).meta
    except ValidationError:
        return None


_SPEC_CLIENT_METHODS: frozenset[str] = frozenset(
    cast(type[BaseModel], arm).model_fields["method"].default for arm in get_args(ClientRequest)
)
"""Method names in the spec `ClientRequest` union, derived from the
discriminator literal on each arm. Used to gate upfront validation so custom
methods registered via `add_request_handler` are not rejected."""


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


@dataclass
class ServerRunner(Generic[LifespanT]):
    """Per-connection orchestrator. One instance per client connection."""

    server: Server[LifespanT]
    dispatcher: JSONRPCDispatcher[Any]
    lifespan_state: LifespanT
    has_standalone_channel: bool
    init_options: InitializationOptions | None = None
    """`InitializeResult` payload. Defaults to `server.create_initialization_options()`."""
    session_id: str | None = None
    stateless: bool = False
    dispatch_middleware: list[DispatchMiddleware] = field(default_factory=list[DispatchMiddleware])

    connection: Connection = field(init=False)
    session: ServerSession = field(init=False)
    """Connection-scoped: the same instance reaches every request as `ctx.session`."""

    def __post_init__(self) -> None:
        if self.init_options is None:
            self.init_options = self.server.create_initialization_options()
        self.connection = Connection(
            self.dispatcher, has_standalone_channel=self.has_standalone_channel, session_id=self.session_id
        )
        if self.stateless:
            # No handshake ever arrives on a stateless connection; born ready.
            self.connection.initialized.set()
        self.session = ServerSession(self.dispatcher, self.connection, stateless=self.stateless)

    async def run(self, *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Drive the dispatcher until the underlying channel closes.

        Composes `dispatch_middleware` over `_on_request` and hands the result
        to `dispatcher.run()`. `task_status.started()` is forwarded so callers
        can `await tg.start(runner.run)` and resume once the dispatcher is
        ready to accept requests. Once the dispatcher exits,
        `connection.exit_stack` is unwound (shielded from outer cancellation,
        bounded by `_EXIT_STACK_CLOSE_TIMEOUT`) so any per-connection cleanup
        registered by handlers or middleware gets a chance to run without a
        misbehaving callback hanging shutdown indefinitely.
        """
        try:
            await self.dispatcher.run(self._compose_on_request(), self._on_notify, task_status=task_status)
        finally:
            with anyio.move_on_after(_EXIT_STACK_CLOSE_TIMEOUT, shield=True) as scope:
                try:
                    await self.connection.exit_stack.aclose()
                except Exception:
                    # Raising here would mask dispatcher.run()'s exception and
                    # crash stdio servers on normal disconnect.
                    logger.exception("connection exit_stack cleanup raised")
            if scope.cancelled_caught:
                logger.warning(
                    "connection exit_stack cleanup exceeded %s seconds; abandoning remaining callbacks",
                    _EXIT_STACK_CLOSE_TIMEOUT,
                )

    def _compose_on_request(self) -> OnRequest:
        """Wrap `_on_request` in `dispatch_middleware`, outermost-first.

        Dispatch-tier middleware sees raw `(dctx, method, params) -> dict`
        and wraps everything - initialize, METHOD_NOT_FOUND, validation
        failures included. `run()` calls this once and hands the result to
        `dispatcher.run()`.
        """
        return reduce(lambda h, mw: mw(h), reversed(self.dispatch_middleware), self._on_request)

    async def _on_request(
        self,
        dctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        ctx = self._make_context(dctx, _extract_meta(params))

        async def _inner() -> HandlerResult:
            # TODO(maxisbey): pinned compat: spec methods are validated against
            # the ClientRequest union before lookup, so malformed params are
            # INVALID_PARAMS even with no handler registered.
            if method in _SPEC_CLIENT_METHODS:
                payload: dict[str, Any] = {"method": method}
                if params is not None:
                    payload["params"] = dict(params)
                client_request_adapter.validate_python(payload, by_name=False)
            # TODO(maxisbey): the 2026-07-28 spec drops the handshake; this branch and
            # the gate become a per-version legacy path then. Initialize runs inline
            # (read loop parked), so awaiting the peer anywhere on this path deadlocks.
            if method == "initialize":
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
        ctx = self._make_context(dctx, _extract_meta(params))

        async def _inner() -> None:
            if method == "notifications/initialized":
                # Validate before committing so a malformed notification leaves
                # state untouched; then fall through so a registered handler
                # observes an initialized connection.
                if params is not None:
                    try:
                        NotificationParams.model_validate(params, by_name=False)
                    except ValidationError:
                        logger.warning("dropped %r: malformed params", method)
                        return
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
        self, dctx: DispatchContext[TransportContext], meta: RequestParamsMeta | None
    ) -> ServerRequestContext[LifespanT, Any]:
        # TODO(maxisbey): remove for Context rework. Reads the SHTTP per-request
        # data off the raw `dctx.message_metadata` carrier; replace with the
        # per-transport context once that lands.
        md = dctx.message_metadata
        if isinstance(md, ServerMessageMetadata):
            request = md.request_context
            close_sse_stream = md.close_sse_stream
            close_standalone_sse_stream = md.close_standalone_sse_stream
        else:
            request = close_sse_stream = close_standalone_sse_stream = None
        return ServerRequestContext(
            session=self.session,
            lifespan_context=self.lifespan_state,
            request_id=dctx.request_id,
            meta=meta,
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
        assert self.init_options is not None
        opts = self.init_options
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
