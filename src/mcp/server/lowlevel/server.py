"""MCP Server Module

This module provides a framework for creating an MCP (Model Context Protocol) server.
It allows you to easily define and handle various types of requests and notifications
using constructor-based handler registration.

Usage:
1. Define handler functions:
   async def my_list_tools(ctx, params):
       return types.ListToolsResult(tools=[...])

   async def my_call_tool(ctx, params):
       return types.CallToolResult(content=[...])

2. Create a Server instance with on_* handlers:
   server = Server(
       "your_server_name",
       on_list_tools=my_list_tools,
       on_call_tool=my_call_tool,
   )

3. Run the server:
   async def main():
       async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
           await server.run(
               read_stream,
               write_stream,
               server.create_initialization_options(),
           )

   asyncio.run(main())

The Server class dispatches incoming requests and notifications to registered
handler callables by method string.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version as importlib_version
from typing import Any, Generic, overload

import mcp_types as types
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount, Route
from typing_extensions import TypeVar, deprecated

from mcp.server._otel import OpenTelemetryMiddleware
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheableMethod, CacheHint, validate_cache_hints
from mcp.server.context import HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.models import InitializationOptions
from mcp.server.runner import serve_dual_era_loop
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

DEFAULT_READ_EOF_DRAIN_TIMEOUT_SECONDS = 1.0

LifespanResultT = TypeVar("LifespanResultT", default=Any)

_ParamsT = TypeVar("_ParamsT", bound=BaseModel, default=BaseModel)

RequestHandler = Callable[[ServerRequestContext[LifespanResultT], _ParamsT], Awaitable[HandlerResult]]
"""A registered request handler: `(ctx, params) -> result`."""

NotificationHandler = Callable[[ServerRequestContext[LifespanResultT], _ParamsT], Awaitable[None]]
"""A registered notification handler: `(ctx, params) -> None`."""


@dataclass(frozen=True, slots=True)
class HandlerEntry(Generic[LifespanResultT]):
    """A registered handler and the params model to validate incoming params against.

    Stored in `Server._request_handlers` / `_notification_handlers` and consumed
    by `ServerRunner` to validate, build `Context`, and invoke. The handler's
    second-argument type is erased to `Any` in storage (each entry has a
    different concrete params type and `Callable` parameters are contravariant);
    the precise type is recoverable via `params_type`. The correlation is
    enforced at registration time by `Server.add_request_handler`.
    """

    params_type: type[BaseModel]
    handler: RequestHandler[LifespanResultT, Any]


class NotificationOptions:
    def __init__(self, prompts_changed: bool = False, resources_changed: bool = False, tools_changed: bool = False):
        self.prompts_changed = prompts_changed
        self.resources_changed = resources_changed
        self.tools_changed = tools_changed


@asynccontextmanager
async def lifespan(_: Server[Any]) -> AsyncIterator[dict[str, Any]]:
    """Default lifespan context manager that does nothing.

    Returns:
        An empty context object
    """
    yield {}


async def _ping_handler(ctx: ServerRequestContext[Any], params: types.RequestParams | None) -> types.EmptyResult:
    return types.EmptyResult()


def _package_version(package: str) -> str:
    try:
        return importlib_version(package)
    except Exception:  # pragma: no cover
        pass

    return "unknown"  # pragma: no cover


class Server(Generic[LifespanResultT]):
    @overload
    def __init__(
        self,
        name: str,
        *,
        version: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[types.Icon] | None = None,
        cache_hints: Mapping[CacheableMethod, CacheHint] | None = None,
        lifespan: Callable[
            [Server[LifespanResultT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
        # Request handlers
        on_list_tools: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListToolsResult],
        ]
        | None = None,
        on_call_tool: Callable[
            [ServerRequestContext[LifespanResultT], types.CallToolRequestParams],
            Awaitable[types.CallToolResult | types.InputRequiredResult],
        ]
        | None = None,
        on_list_resources: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourcesResult],
        ]
        | None = None,
        on_list_resource_templates: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourceTemplatesResult],
        ]
        | None = None,
        on_read_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.ReadResourceRequestParams],
            Awaitable[types.ReadResourceResult | types.InputRequiredResult],
        ]
        | None = None,
        on_subscribe_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.SubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_unsubscribe_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.UnsubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_subscriptions_listen: Callable[
            [ServerRequestContext[LifespanResultT], types.SubscriptionsListenRequestParams],
            Awaitable[types.SubscriptionsListenResult],
        ]
        | None = None,
        on_list_prompts: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListPromptsResult],
        ]
        | None = None,
        on_get_prompt: Callable[
            [ServerRequestContext[LifespanResultT], types.GetPromptRequestParams],
            Awaitable[types.GetPromptResult | types.InputRequiredResult],
        ]
        | None = None,
        on_completion: Callable[
            [ServerRequestContext[LifespanResultT], types.CompleteRequestParams],
            Awaitable[types.CompleteResult],
        ]
        | None = None,
        on_ping: Callable[
            [ServerRequestContext[LifespanResultT], types.RequestParams | None],
            Awaitable[types.EmptyResult],
        ] = _ping_handler,
    ) -> None: ...
    @overload
    @deprecated(
        "on_set_logging_level (Logging) and on_roots_list_changed (Roots) are deprecated as of 2026-07-28 "
        "(SEP-2577); on_progress (client-to-server progress) is deprecated as of 2026-07-28. Passing any of "
        "them emits an MCPDeprecationWarning at runtime.",
        category=MCPDeprecationWarning,
    )
    def __init__(
        self,
        name: str,
        *,
        version: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[types.Icon] | None = None,
        cache_hints: Mapping[CacheableMethod, CacheHint] | None = None,
        lifespan: Callable[
            [Server[LifespanResultT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
        # Request handlers
        on_list_tools: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListToolsResult],
        ]
        | None = None,
        on_call_tool: Callable[
            [ServerRequestContext[LifespanResultT], types.CallToolRequestParams],
            Awaitable[types.CallToolResult | types.InputRequiredResult],
        ]
        | None = None,
        on_list_resources: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourcesResult],
        ]
        | None = None,
        on_list_resource_templates: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourceTemplatesResult],
        ]
        | None = None,
        on_read_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.ReadResourceRequestParams],
            Awaitable[types.ReadResourceResult | types.InputRequiredResult],
        ]
        | None = None,
        on_subscribe_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.SubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_unsubscribe_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.UnsubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_subscriptions_listen: Callable[
            [ServerRequestContext[LifespanResultT], types.SubscriptionsListenRequestParams],
            Awaitable[types.SubscriptionsListenResult],
        ]
        | None = None,
        on_list_prompts: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListPromptsResult],
        ]
        | None = None,
        on_get_prompt: Callable[
            [ServerRequestContext[LifespanResultT], types.GetPromptRequestParams],
            Awaitable[types.GetPromptResult | types.InputRequiredResult],
        ]
        | None = None,
        on_completion: Callable[
            [ServerRequestContext[LifespanResultT], types.CompleteRequestParams],
            Awaitable[types.CompleteResult],
        ]
        | None = None,
        on_set_logging_level: Callable[
            [ServerRequestContext[LifespanResultT], types.SetLevelRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_ping: Callable[
            [ServerRequestContext[LifespanResultT], types.RequestParams | None],
            Awaitable[types.EmptyResult],
        ] = _ping_handler,
        # Notification handlers
        on_roots_list_changed: Callable[
            [ServerRequestContext[LifespanResultT], types.NotificationParams | None],
            Awaitable[None],
        ]
        | None = None,
        on_progress: Callable[
            [ServerRequestContext[LifespanResultT], types.ProgressNotificationParams],
            Awaitable[None],
        ]
        | None = None,
    ) -> None: ...
    def __init__(
        self,
        name: str,
        *,
        version: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[types.Icon] | None = None,
        cache_hints: Mapping[CacheableMethod, CacheHint] | None = None,
        lifespan: Callable[
            [Server[LifespanResultT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
        # Request handlers
        on_list_tools: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListToolsResult],
        ]
        | None = None,
        on_call_tool: Callable[
            [ServerRequestContext[LifespanResultT], types.CallToolRequestParams],
            Awaitable[types.CallToolResult | types.InputRequiredResult],
        ]
        | None = None,
        on_list_resources: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourcesResult],
        ]
        | None = None,
        on_list_resource_templates: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourceTemplatesResult],
        ]
        | None = None,
        on_read_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.ReadResourceRequestParams],
            Awaitable[types.ReadResourceResult | types.InputRequiredResult],
        ]
        | None = None,
        on_subscribe_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.SubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_unsubscribe_resource: Callable[
            [ServerRequestContext[LifespanResultT], types.UnsubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_subscriptions_listen: Callable[
            [ServerRequestContext[LifespanResultT], types.SubscriptionsListenRequestParams],
            Awaitable[types.SubscriptionsListenResult],
        ]
        | None = None,
        on_list_prompts: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListPromptsResult],
        ]
        | None = None,
        on_get_prompt: Callable[
            [ServerRequestContext[LifespanResultT], types.GetPromptRequestParams],
            Awaitable[types.GetPromptResult | types.InputRequiredResult],
        ]
        | None = None,
        on_completion: Callable[
            [ServerRequestContext[LifespanResultT], types.CompleteRequestParams],
            Awaitable[types.CompleteResult],
        ]
        | None = None,
        on_set_logging_level: Callable[
            [ServerRequestContext[LifespanResultT], types.SetLevelRequestParams],
            Awaitable[types.EmptyResult],
        ]
        | None = None,
        on_ping: Callable[
            [ServerRequestContext[LifespanResultT], types.RequestParams | None],
            Awaitable[types.EmptyResult],
        ] = _ping_handler,
        # Notification handlers
        on_roots_list_changed: Callable[
            [ServerRequestContext[LifespanResultT], types.NotificationParams | None],
            Awaitable[None],
        ]
        | None = None,
        on_progress: Callable[
            [ServerRequestContext[LifespanResultT], types.ProgressNotificationParams],
            Awaitable[None],
        ]
        | None = None,
    ) -> None:
        if on_set_logging_level is not None:
            warnings.warn(
                "The logging capability is deprecated as of 2026-07-28 (SEP-2577).",
                MCPDeprecationWarning,
                stacklevel=2,
            )
        if on_roots_list_changed is not None:
            warnings.warn(
                "The roots capability is deprecated as of 2026-07-28 (SEP-2577).",
                MCPDeprecationWarning,
                stacklevel=2,
            )
        if on_progress is not None:
            warnings.warn(
                "Client-to-server progress is deprecated as of 2026-07-28.",
                MCPDeprecationWarning,
                stacklevel=2,
            )

        self.name = name
        self.version = version
        self.title = title
        self.description = description
        self.instructions = instructions
        self.website_url = website_url
        self.icons = icons
        # Per-method `ttl_ms`/`cache_scope` fills, applied by `ServerRunner`
        # after the handler returns; fields the handler set explicitly win.
        self.cache_hints: dict[str, CacheHint] = validate_cache_hints(cache_hints)
        self.lifespan = lifespan
        self._request_handlers: dict[str, HandlerEntry[LifespanResultT]] = {}
        self._notification_handlers: dict[str, HandlerEntry[LifespanResultT]] = {}
        self._session_manager: StreamableHTTPSessionManager | None = None
        # Context-tier middleware: wraps every inbound request (including
        # `initialize`, lookup, validation, handler) with
        # `(ctx, call_next)`. Applied in `ServerRunner._on_request`.
        # `OpenTelemetryMiddleware` ships on by default so every server emits a
        # SERVER span per message; it is a no-op until an OTel exporter is
        # installed. Drop it from this list to opt out.
        # TODO(L54): provisional - signature and semantics change with the
        # Context/middleware rework (covariant `Context[L]`, outbound seam) before
        # v2 final.
        self.middleware: list[ServerMiddleware[LifespanResultT]] = [OpenTelemetryMiddleware()]
        # SEP-2133 extension settings advertised under `ServerCapabilities.extensions`
        # (identifier -> settings). Higher layers (e.g. `MCPServer(extensions=...)`)
        # populate it; `get_capabilities` reads it when no explicit map is passed.
        self.extensions: dict[str, dict[str, Any]] = {}
        logger.debug("Initializing server %r", name)

        _spec_requests: list[tuple[str, type[BaseModel], RequestHandler[LifespanResultT, Any] | None]] = [
            ("ping", types.RequestParams, on_ping),
            ("server/discover", types.RequestParams, self._handle_discover),
            ("prompts/list", types.PaginatedRequestParams, on_list_prompts),
            ("prompts/get", types.GetPromptRequestParams, on_get_prompt),
            ("resources/list", types.PaginatedRequestParams, on_list_resources),
            ("resources/templates/list", types.PaginatedRequestParams, on_list_resource_templates),
            ("resources/read", types.ReadResourceRequestParams, on_read_resource),
            ("resources/subscribe", types.SubscribeRequestParams, on_subscribe_resource),
            ("resources/unsubscribe", types.UnsubscribeRequestParams, on_unsubscribe_resource),
            ("subscriptions/listen", types.SubscriptionsListenRequestParams, on_subscriptions_listen),
            ("tools/list", types.PaginatedRequestParams, on_list_tools),
            ("tools/call", types.CallToolRequestParams, on_call_tool),
            ("logging/setLevel", types.SetLevelRequestParams, on_set_logging_level),
            ("completion/complete", types.CompleteRequestParams, on_completion),
        ]
        self._request_handlers.update({m: HandlerEntry(pt, h) for m, pt, h in _spec_requests if h is not None})

        _spec_notifications: list[tuple[str, type[BaseModel], NotificationHandler[LifespanResultT, Any] | None]] = [
            ("notifications/roots/list_changed", types.NotificationParams, on_roots_list_changed),
            ("notifications/progress", types.ProgressNotificationParams, on_progress),
        ]
        self._notification_handlers.update(
            {m: HandlerEntry(pt, h) for m, pt, h in _spec_notifications if h is not None}
        )

    def add_request_handler(
        self,
        method: str,
        params_type: type[_ParamsT],
        handler: RequestHandler[LifespanResultT, _ParamsT],
    ) -> None:
        """Register a request handler for `method`.

        `params_type` is the model incoming params are validated against
        before the handler is invoked. It should subclass `RequestParams` so
        `_meta` parses uniformly. A message with no `params` member validates
        `{}` against `params_type`: models with required fields reject it as
        INVALID_PARAMS, all-optional models reach the handler with their
        defaults - the handler never receives `None`. Replaces any existing
        handler for the same method, except `initialize`, which is reserved:
        the runner owns the handshake, so registering it raises `ValueError`.
        Use `Server.middleware` to observe or wrap initialization.
        """
        if method == "initialize":
            raise ValueError(
                "'initialize' is handled by the server runner and cannot be overridden; "
                "use Server.middleware to observe or wrap initialization"
            )
        self._request_handlers[method] = HandlerEntry(params_type, handler)

    def add_notification_handler(
        self,
        method: str,
        params_type: type[_ParamsT],
        handler: NotificationHandler[LifespanResultT, _ParamsT],
    ) -> None:
        """Register a notification handler for `method`.

        `params_type` should subclass `NotificationParams` so `_meta`
        parses uniformly. Absent params follow the same contract as requests:
        `{}` is validated, so the handler receives the model with its defaults,
        never `None`. Replaces any existing handler. A handler for
        `notifications/initialized` runs after the runner has marked the
        connection initialized.
        """
        self._notification_handlers[method] = HandlerEntry(params_type, handler)

    def get_request_handler(self, method: str) -> HandlerEntry[LifespanResultT] | None:
        """Return the registered entry for a request method, or `None`."""
        return self._request_handlers.get(method)

    def get_notification_handler(self, method: str) -> HandlerEntry[LifespanResultT] | None:
        """Return the registered entry for a notification method, or `None`."""
        return self._notification_handlers.get(method)

    # TODO(L53): Rethink capabilities API. Currently capabilities are derived from registered
    # handlers but require NotificationOptions to be passed externally for list_changed
    # flags, and experimental_capabilities as a separate dict. Consider deriving capabilities
    # entirely from server state (e.g. constructor params for list_changed) instead of
    # requiring callers to assemble them at create_initialization_options() time.
    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
    ) -> InitializationOptions:
        """Create initialization options from this server instance.

        `extensions` advertises SEP-2133 extension support under
        `ServerCapabilities.extensions`; keys are extension identifiers (e.g.
        `io.modelcontextprotocol/ui`), values are per-extension settings.
        Defaults to `self.extensions`, which higher layers populate.
        """
        return InitializationOptions(
            server_name=self.name,
            server_version=self.version if self.version else _package_version("mcp"),
            title=self.title,
            description=self.description,
            capabilities=self.get_capabilities(
                notification_options or NotificationOptions(),
                experimental_capabilities or {},
                extensions if extensions is not None else self.extensions,
            ),
            instructions=self.instructions,
            website_url=self.website_url,
            icons=self.icons,
        )

    def get_capabilities(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
        *,
        protocol_version: str | None = None,
    ) -> types.ServerCapabilities:
        """Convert existing handlers to a ServerCapabilities object.

        `extensions` is the SEP-2133 extension map (identifier -> settings)
        advertised under `ServerCapabilities.extensions`; it defaults to
        `self.extensions`.

        `protocol_version` makes the subscription-delivered bits era-honest:
        at 2026-07-28+ versions, change notifications are delivered only on
        `subscriptions/listen` streams, so the `listChanged` flags and
        `resources.subscribe` derive from whether that method is served -
        `notification_options` and the legacy `resources/subscribe` handler
        (which the modern wire cannot dispatch) are ignored. When omitted, the
        handshake-era derivation applies unchanged.
        """
        notification_options = notification_options or NotificationOptions()
        prompts_capability = None
        resources_capability = None
        tools_capability = None
        logging_capability = None
        completions_capability = None

        if protocol_version in MODERN_PROTOCOL_VERSIONS:
            listen_served = "subscriptions/listen" in self._request_handlers
            prompts_changed = tools_changed = resources_changed = subscribe = listen_served
        else:
            prompts_changed = notification_options.prompts_changed
            tools_changed = notification_options.tools_changed
            resources_changed = notification_options.resources_changed
            subscribe = "resources/subscribe" in self._request_handlers

        # Set prompt capabilities if handler exists
        if "prompts/list" in self._request_handlers:
            prompts_capability = types.PromptsCapability(list_changed=prompts_changed)

        # Set resource capabilities if handler exists
        if "resources/list" in self._request_handlers:
            resources_capability = types.ResourcesCapability(
                subscribe=subscribe,
                list_changed=resources_changed,
            )

        # Set tool capabilities if handler exists
        if "tools/list" in self._request_handlers:
            tools_capability = types.ToolsCapability(list_changed=tools_changed)

        # Set logging capabilities if handler exists
        if "logging/setLevel" in self._request_handlers:
            logging_capability = types.LoggingCapability()

        # Set completions capabilities if handler exists
        if "completion/complete" in self._request_handlers:
            completions_capability = types.CompletionsCapability()

        capabilities = types.ServerCapabilities(
            prompts=prompts_capability,
            resources=resources_capability,
            tools=tools_capability,
            logging=logging_capability,
            experimental=experimental_capabilities,
            extensions=extensions if extensions is not None else (self.extensions or None),
            completions=completions_capability,
        )
        return capabilities

    @property
    def server_info(self) -> types.Implementation:
        """The `serverInfo` block describing this implementation.

        Derived from the constructor's identity fields. `version` falls back to
        the installed `mcp` package version when not supplied explicitly.
        """
        return types.Implementation(
            name=self.name,
            version=self.version if self.version else _package_version("mcp"),
            title=self.title,
            description=self.description,
            website_url=self.website_url,
            icons=self.icons,
        )

    async def _handle_discover(
        self, ctx: ServerRequestContext[LifespanResultT], params: types.RequestParams | None
    ) -> types.DiscoverResult:
        """Default `server/discover` handler.

        Auto-derived from server state at call time, so capabilities reflect
        whatever has been registered (constructor `on_*` kwargs and later
        `add_request_handler` calls). Operators can replace it wholesale via
        `add_request_handler("server/discover", ...)`. Reachability for legacy
        peers is decided at the boundary (`types.methods`), not here.
        """
        return types.DiscoverResult(
            supported_versions=list(MODERN_PROTOCOL_VERSIONS),
            capabilities=self.get_capabilities(protocol_version=ctx.protocol_version),
            server_info=self.server_info,
            instructions=self.instructions,
        )

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """Get the StreamableHTTP session manager.

        Raises:
            RuntimeError: If called before streamable_http_app() has been called.
        """
        if self._session_manager is None:
            raise RuntimeError(  # pragma: no cover
                "Session manager can only be accessed after calling streamable_http_app(). "
                "The session manager is created lazily to avoid unnecessary initialization."
            )
        return self._session_manager

    async def run(
        self,
        read_stream: ReadStream[SessionMessage | Exception],
        write_stream: WriteStream[SessionMessage],
        initialization_options: InitializationOptions,
        # When False, exceptions are returned as messages to the client.
        # When True, exceptions are raised, which will cause the server to shut down
        # but also make tracing exceptions much easier during testing and when using
        # in-process servers.
        raise_exceptions: bool = False,
        # When True, the server is stateless and
        # clients can perform initialization with any node. The client must still follow
        # the initialization lifecycle, but can do so with any available node
        # rather than requiring initialization for each connection.
        stateless: bool = False,
        # When True, treat read EOF as a half-close and allow in-flight handlers
        # to drain their responses via the still-open write stream (e.g. stdio
        # with bash-redirected stdin).
        drain_on_read_close: bool = False,
        # Maximum time to wait for in-flight handlers to drain after read EOF.
        # None means wait indefinitely.
        read_eof_drain_timeout_seconds: float | None = DEFAULT_READ_EOF_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        """Serve a single connection over the given streams until the read side closes.

        Thin wrapper over `serve_dual_era_loop`: enters the server lifespan,
        then drives the loop, serving the legacy handshake era and the modern
        per-request-envelope era (the first era-distinctive message to succeed
        locks the connection). Transports with their own lifespan owner (the
        streamable-HTTP manager) call `serve_loop` directly instead.
        """
        async with self.lifespan(self) as lifespan_context:
            await serve_dual_era_loop(
                self,
                read_stream,
                write_stream,
                lifespan_state=lifespan_context,
                init_options=initialization_options,
                raise_exceptions=raise_exceptions,
                session_id=None,
                close_write_stream_on_read_close=not drain_on_read_close,
                read_eof_drain_timeout_seconds=read_eof_drain_timeout_seconds,
            )

    def streamable_http_app(
        self,
        *,
        streamable_http_path: str = "/mcp",
        json_response: bool = False,
        stateless_http: bool = False,
        event_store: EventStore | None = None,
        retry_interval: int | None = None,
        transport_security: TransportSecuritySettings | None = None,
        host: str = "127.0.0.1",
        auth: AuthSettings | None = None,
        token_verifier: TokenVerifier | None = None,
        auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
        custom_starlette_routes: list[Route] | None = None,
        debug: bool = False,
    ) -> Starlette:
        """Return an instance of the StreamableHTTP server app."""
        # Auto-enable DNS rebinding protection for localhost (IPv4 and IPv6)
        if transport_security is None and host in ("127.0.0.1", "localhost", "::1"):
            transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
            )

        session_manager = StreamableHTTPSessionManager(
            app=self,
            event_store=event_store,
            retry_interval=retry_interval,
            json_response=json_response,
            stateless=stateless_http,
            security_settings=transport_security,
        )
        self._session_manager = session_manager

        # Create the ASGI handler
        streamable_http_app = StreamableHTTPASGIApp(session_manager)

        # Create routes
        routes: list[Route | Mount] = []
        middleware: list[Middleware] = []
        required_scopes: list[str] = []

        # Set up auth if configured
        if auth:
            required_scopes = auth.required_scopes or []

            # Add auth middleware if token verifier is available
            if token_verifier:
                middleware = [
                    Middleware(
                        AuthenticationMiddleware,
                        backend=BearerAuthBackend(token_verifier),
                    ),
                    Middleware(AuthContextMiddleware),
                ]

            # Add auth endpoints if auth server provider is configured
            if auth_server_provider:
                routes.extend(
                    create_auth_routes(
                        provider=auth_server_provider,
                        issuer_url=auth.issuer_url,
                        service_documentation_url=auth.service_documentation_url,
                        client_registration_options=auth.client_registration_options,
                        revocation_options=auth.revocation_options,
                        identity_assertion_enabled=auth.identity_assertion_enabled,
                    )
                )

        # Set up routes with or without auth
        if token_verifier:
            # Determine resource metadata URL
            resource_metadata_url = None
            if auth and auth.resource_server_url:  # pragma: no branch
                # Build compliant metadata URL for WWW-Authenticate header
                resource_metadata_url = build_resource_metadata_url(auth.resource_server_url)

            routes.append(
                Route(
                    streamable_http_path,
                    endpoint=RequireAuthMiddleware(streamable_http_app, required_scopes, resource_metadata_url),
                )
            )
        else:
            # Auth is disabled, no wrapper needed
            routes.append(
                Route(
                    streamable_http_path,
                    endpoint=streamable_http_app,
                )
            )

        # Add protected resource metadata endpoint if configured as RS
        if auth and auth.resource_server_url:
            routes.extend(
                create_protected_resource_routes(
                    resource_url=auth.resource_server_url,
                    authorization_servers=[auth.issuer_url],
                    scopes_supported=auth.required_scopes,
                )
            )

        if custom_starlette_routes:
            routes.extend(custom_starlette_routes)

        return Starlette(
            debug=debug,
            routes=routes,
            middleware=middleware,
            lifespan=lambda app: session_manager.run(),
        )
