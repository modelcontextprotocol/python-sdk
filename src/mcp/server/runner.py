"""`ServerRunner` — per-connection orchestrator over a `Dispatcher`.

`ServerRunner` is the bridge between the dispatcher layer (`on_request` /
`on_notify`, untyped dicts) and the user's handler layer (typed `Context`,
typed params). One instance per client connection. It:

* handles the ``initialize`` handshake and populates `Connection`
* gates requests until initialized (``ping`` exempt)
* looks up the handler in the server's registry, validates params, builds
  `Context`, runs the middleware chain, returns the result dict
* drives ``dispatcher.run()`` and the per-connection lifespan

`ServerRunner` consumes any `ServerRegistry` — the lowlevel `Server` satisfies
it via additive methods so the existing ``Server.run()`` path is unaffected.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, cast

from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server.connection import Connection
from mcp.server.context import Context
from mcp.server.lowlevel.server import NotificationOptions
from mcp.shared.dispatcher import DispatchContext, Dispatcher
from mcp.shared.exceptions import MCPError
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    CompleteRequestParams,
    GetPromptRequestParams,
    Implementation,
    InitializeRequestParams,
    InitializeResult,
    NotificationParams,
    PaginatedRequestParams,
    ProgressNotificationParams,
    ReadResourceRequestParams,
    RequestParams,
    ServerCapabilities,
    SetLevelRequestParams,
    SubscribeRequestParams,
    UnsubscribeRequestParams,
)

__all__ = ["ServerRegistry", "ServerRunner"]

logger = logging.getLogger(__name__)

LifespanT = TypeVar("LifespanT", default=Any)
ServerTransportT = TypeVar("ServerTransportT", bound=TransportContext, default=TransportContext)

Handler = Callable[..., Awaitable[Any]]
"""A request/notification handler: ``(ctx, params) -> result``. Typed loosely
so the existing `ServerRequestContext`-based handlers and the new
`Context`-based handlers both fit during the transition.
"""

_INIT_EXEMPT: frozenset[str] = frozenset({"ping"})

# TODO: remove this lookup once `Server` stores (params_type, handler) in its
# registry directly. This is scaffolding so ServerRunner can validate params
# without changing the existing `_request_handlers` dict shape.
_PARAMS_FOR_METHOD: dict[str, type[BaseModel]] = {
    "ping": RequestParams,
    "tools/list": PaginatedRequestParams,
    "tools/call": CallToolRequestParams,
    "prompts/list": PaginatedRequestParams,
    "prompts/get": GetPromptRequestParams,
    "resources/list": PaginatedRequestParams,
    "resources/templates/list": PaginatedRequestParams,
    "resources/read": ReadResourceRequestParams,
    "resources/subscribe": SubscribeRequestParams,
    "resources/unsubscribe": UnsubscribeRequestParams,
    "logging/setLevel": SetLevelRequestParams,
    "completion/complete": CompleteRequestParams,
}
"""Spec method → params model. Scaffolding while the lowlevel `Server`'s
`_request_handlers` stores handler-only; the registry refactor should make this
the registry's responsibility (or store params types alongside handlers)."""

_PARAMS_FOR_NOTIFICATION: dict[str, type[BaseModel]] = {
    "notifications/initialized": NotificationParams,
    "notifications/roots/list_changed": NotificationParams,
    "notifications/progress": ProgressNotificationParams,
}


class ServerRegistry(Protocol):
    """The handler registry `ServerRunner` consumes.

    The lowlevel `Server` satisfies this via additive methods.
    """

    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str | None: ...

    def get_request_handler(self, method: str) -> Handler | None: ...
    def get_notification_handler(self, method: str) -> Handler | None: ...
    def get_capabilities(
        self, notification_options: Any, experimental_capabilities: dict[str, dict[str, Any]]
    ) -> ServerCapabilities: ...


def _dump_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    if isinstance(result, dict):
        return cast(dict[str, Any], result)
    raise TypeError(f"handler returned {type(result).__name__}; expected BaseModel, dict, or None")


@dataclass
class ServerRunner(Generic[LifespanT, ServerTransportT]):
    """Per-connection orchestrator. One instance per client connection."""

    server: ServerRegistry
    dispatcher: Dispatcher[ServerTransportT]
    lifespan_state: LifespanT
    has_standalone_channel: bool
    stateless: bool = False

    connection: Connection = field(init=False)
    _initialized: bool = field(init=False)

    def __post_init__(self) -> None:
        self._initialized = self.stateless
        self.connection = Connection(self.dispatcher, has_standalone_channel=self.has_standalone_channel)

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
        handler = self.server.get_request_handler(method)
        if handler is None:
            raise MCPError(code=METHOD_NOT_FOUND, message=f"Method not found: {method}")
        # TODO: scaffolding — params_type comes from a static lookup until the
        # registry stores it alongside the handler.
        params_type = _PARAMS_FOR_METHOD.get(method, RequestParams)
        # ValidationError propagates; the dispatcher's exception boundary maps
        # it to INVALID_PARAMS.
        typed_params = params_type.model_validate(params or {})
        ctx = self._make_context(dctx, typed_params)
        result = await handler(ctx, typed_params)
        return _dump_result(result)

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
        handler = self.server.get_notification_handler(method)
        if handler is None:
            logger.debug("no handler for notification %s", method)
            return
        params_type = _PARAMS_FOR_NOTIFICATION.get(method, NotificationParams)
        typed_params = params_type.model_validate(params or {})
        ctx = self._make_context(dctx, typed_params)
        await handler(ctx, typed_params)

    def _make_context(
        self, dctx: DispatchContext[TransportContext], typed_params: BaseModel
    ) -> Context[LifespanT, ServerTransportT]:
        # `OnRequest` delivers `DispatchContext[TransportContext]`; this
        # ServerRunner instance was constructed for a specific
        # `ServerTransportT`, so the narrow is safe by construction.
        narrowed = cast(DispatchContext[ServerTransportT], dctx)
        meta = getattr(typed_params, "meta", None)
        return Context(narrowed, lifespan=self.lifespan_state, connection=self.connection, meta=meta)

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
            capabilities=self.server.get_capabilities(NotificationOptions(), {}),
            server_info=Implementation(name=self.server.name, version=self.server.version or "0.0.0"),
        )
        return _dump_result(result)
