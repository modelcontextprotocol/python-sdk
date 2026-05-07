"""`ServerRunner` — per-connection orchestrator over a `Dispatcher`.

`ServerRunner` is the bridge between the dispatcher layer (`on_request` /
`on_notify`, untyped dicts) and the user's handler layer (typed `Context`,
typed params). One instance per client connection. It:

* handles the ``initialize`` handshake and populates `Connection`
* gates requests until initialized (``ping`` exempt)
* looks up the handler in the server's registry, validates params, builds
  `Context`, runs the middleware chain, returns the result dict
* drives ``dispatcher.run()`` and the per-connection lifespan

`ServerRunner` holds a `Server` directly — `Server` is the registry.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial, reduce
from typing import Any, Generic, cast

import anyio.abc
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server.connection import Connection
from mcp.server.context import CallNext, Context, ServerMiddleware
from mcp.server.lowlevel.server import Server
from mcp.shared._otel import extract_trace_context, otel_span
from mcp.shared.dispatcher import DispatchContext, Dispatcher, DispatchMiddleware, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
)

__all__ = ["CallNext", "ServerMiddleware", "ServerRunner", "otel_middleware"]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)


_INIT_EXEMPT: frozenset[str] = frozenset({"ping"})


def otel_middleware(next_on_request: OnRequest) -> OnRequest:
    """Dispatch-tier middleware that wraps each request in an OpenTelemetry span.

    Mirrors the span shape of the existing `Server._handle_request`: span name
    ``"MCP handle <method> [<target>]"``, ``mcp.method.name`` attribute, W3C
    trace context extracted from ``params._meta`` (SEP-414), and an ERROR
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
        with otel_span(
            span_name,
            kind=SpanKind.SERVER,
            attributes={"mcp.method.name": method},
            context=parent,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                return await next_on_request(dctx, method, params)
            except MCPError as e:
                span.set_status(StatusCode.ERROR, e.error.message)
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                raise

    return wrapped


def _dump_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    if isinstance(result, dict):
        return cast(dict[str, Any], result)
    raise TypeError(f"handler returned {type(result).__name__}; expected BaseModel, dict, or None")


@dataclass
class ServerRunner(Generic[LifespanT]):
    """Per-connection orchestrator. One instance per client connection."""

    server: Server[LifespanT]
    dispatcher: Dispatcher[TransportContext]
    lifespan_state: LifespanT
    has_standalone_channel: bool
    session_id: str | None = None
    stateless: bool = False
    dispatch_middleware: list[DispatchMiddleware] = field(default_factory=list[DispatchMiddleware])

    connection: Connection = field(init=False)
    _initialized: bool = field(init=False)

    def __post_init__(self) -> None:
        self._initialized = self.stateless
        self.connection = Connection(
            self.dispatcher, has_standalone_channel=self.has_standalone_channel, session_id=self.session_id
        )

    async def run(self, *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Drive the dispatcher until the underlying channel closes.

        Composes `dispatch_middleware` over `_on_request` and hands the result
        to `dispatcher.run()`. ``task_status.started()`` is forwarded so callers
        can ``await tg.start(runner.run)`` and resume once the dispatcher is
        ready to accept requests. Once the dispatcher exits,
        `connection.exit_stack` is unwound (shielded) so any per-connection
        cleanup registered by handlers or middleware runs to completion.
        """
        try:
            await self.dispatcher.run(self._compose_on_request(), self._on_notify, task_status=task_status)
        finally:
            with anyio.CancelScope(shield=True):
                await self.connection.exit_stack.aclose()

    def _compose_on_request(self) -> OnRequest:
        """Wrap `_on_request` in `dispatch_middleware`, outermost-first.

        Dispatch-tier middleware sees raw ``(dctx, method, params) -> dict``
        and wraps everything — initialize, METHOD_NOT_FOUND, validation
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
        if method == "initialize":
            return self._handle_initialize(params)
        if not self._initialized and method not in _INIT_EXEMPT:
            raise MCPError(
                code=INVALID_REQUEST,
                message=f"Received {method!r} before initialization was complete",
            )
        entry = self.server.get_request_handler(method)
        if entry is None:
            raise MCPError(code=METHOD_NOT_FOUND, message=f"Method not found: {method}")
        # ValidationError propagates; the dispatcher's exception boundary maps
        # it to INVALID_PARAMS.
        typed_params = entry.params_type.model_validate(params or {})
        ctx = self._make_context(dctx, typed_params)
        # TODO: cast goes away when `ServerRequestContext = Context` lands.
        call: CallNext = partial(cast(Any, entry.handler), ctx, typed_params)
        for mw in reversed(self.server.middleware):
            call = partial(mw, ctx, method, typed_params, call)
        return _dump_result(await call())

    async def _on_notify(
        self,
        dctx: DispatchContext[TransportContext],
        method: str,
        params: Mapping[str, Any] | None,
    ) -> None:
        if method == "notifications/initialized":
            self._initialized = True
            self.connection.initialized.set()
            return
        if not self._initialized:
            logger.debug("dropped %s: received before initialization", method)
            return
        entry = self.server.get_notification_handler(method)
        if entry is None:
            logger.debug("no handler for notification %s", method)
            return
        typed_params = entry.params_type.model_validate(params or {})
        ctx = self._make_context(dctx, typed_params)
        # TODO: cast goes away when `ServerRequestContext = Context` lands.
        await cast(Any, entry.handler)(ctx, typed_params)

    def _make_context(self, dctx: DispatchContext[TransportContext], typed_params: BaseModel) -> Context[LifespanT]:
        meta = getattr(typed_params, "meta", None)
        return Context(dctx, lifespan=self.lifespan_state, connection=self.connection, meta=meta)

    def _handle_initialize(self, params: Mapping[str, Any] | None) -> dict[str, Any]:
        init = InitializeRequestParams.model_validate(params or {})
        self.connection.client_info = init.client_info
        self.connection.client_capabilities = init.capabilities
        # TODO: real version negotiation. This always responds with LATEST,
        # which is wrong — the server should pick the highest version both
        # sides support and compute a per-connection feature set from it.
        # See FOLLOWUPS: "Consolidate per-connection mode/negotiation".
        self.connection.protocol_version = (
            init.protocol_version if init.protocol_version in {LATEST_PROTOCOL_VERSION} else LATEST_PROTOCOL_VERSION
        )
        self._initialized = True
        self.connection.initialized.set()
        result = InitializeResult(
            protocol_version=self.connection.protocol_version,
            capabilities=self.server.capabilities(),
            server_info=Implementation(name=self.server.name, version=self.server.version or "0.0.0"),
        )
        return _dump_result(result)
