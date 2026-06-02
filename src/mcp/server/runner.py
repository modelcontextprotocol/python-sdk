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
from typing import Any, Generic, cast, get_args

import anyio.abc
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server.connection import Connection
from mcp.server.context import CallNext, Context, ServerMiddleware
from mcp.server.lowlevel.server import Server
from mcp.server.models import InitializationOptions
from mcp.shared._otel import extract_trace_context, otel_span
from mcp.shared.dispatcher import DispatchContext, Dispatcher, DispatchMiddleware, OnRequest
from mcp.shared.exceptions import MCPError
from mcp.shared.transport_context import TransportContext
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    ClientRequest,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    client_request_adapter,
)

__all__ = ["CallNext", "ServerMiddleware", "ServerRunner", "otel_middleware"]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)


_INIT_EXEMPT: frozenset[str] = frozenset({"ping"})

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
    init_options: InitializationOptions | None = None
    """`InitializeResult` payload. Defaults to `server.create_initialization_options()`."""
    session_id: str | None = None
    stateless: bool = False
    dispatch_middleware: list[DispatchMiddleware] = field(default_factory=list[DispatchMiddleware])

    connection: Connection = field(init=False)
    _initialized: bool = field(init=False)

    def __post_init__(self) -> None:
        self._initialized = self.stateless
        if self.init_options is None:
            self.init_options = self.server.create_initialization_options()
        self.connection = Connection(
            self.dispatcher, has_standalone_channel=self.has_standalone_channel, session_id=self.session_id
        )

    async def run(self, *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Drive the dispatcher until the underlying channel closes.

        Composes `dispatch_middleware` over `_on_request` and hands the result
        to `dispatcher.run()`. `task_status.started()` is forwarded so callers
        can `await tg.start(runner.run)` and resume once the dispatcher is
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
        # TODO(maxisbey): pinned compat. `BaseSession._receive_loop` validates
        # every inbound request against the spec `ClientRequest` discriminated
        # union *before* handler lookup, so a spec method with malformed params
        # surfaces as INVALID_PARAMS via the dispatcher's ValidationError
        # boundary even when no handler is registered. v2 wanted to decouple
        # the runner from the spec union; revisit once the suite's divergence
        # entry is resolved. Gated on spec methods so custom methods registered
        # via `add_request_handler` still route (the existing server rejects
        # those too, but nothing pins that and routing them is strictly better).
        if method in _SPEC_CLIENT_METHODS:
            payload: dict[str, Any] = {"method": method}
            if params is not None:
                payload["params"] = dict(params)
            client_request_adapter.validate_python(payload)
        if method == "initialize":
            return self._handle_initialize(params)
        if not self._initialized and method not in _INIT_EXEMPT:
            # TODO(maxisbey): pinned compat. The existing server has no
            # dedicated pre-init check; the request dies in ClientRequest
            # validation, so the client sees the generic invalid-params shape.
            raise MCPError(code=INVALID_PARAMS, message="Invalid request parameters", data="")
        entry = self.server.get_request_handler(method)
        if entry is None:
            raise MCPError(code=METHOD_NOT_FOUND, message="Method not found")
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
        requested = init.protocol_version
        negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        self.connection.protocol_version = negotiated
        self._initialized = True
        self.connection.initialized.set()
        assert self.init_options is not None
        opts = self.init_options
        result = InitializeResult(
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
        return _dump_result(result)
