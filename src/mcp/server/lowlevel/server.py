"""Low-level MCP server framework.

The `Server` class dispatches incoming requests and notifications to handler
callables registered by method string (constructor `on_*` kwargs or
`add_request_handler`/`add_notification_handler`).
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
from mcp.server.runner import serve_loop
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

LifespanResultT = TypeVar("LifespanResultT", default=Any)

_ParamsT = TypeVar("_ParamsT", bound=BaseModel, default=BaseModel)

RequestHandler = Callable[[ServerRequestContext[LifespanResultT], _ParamsT], Awaitable[HandlerResult]]
"""A registered request handler: `(ctx, params) -> result`."""

NotificationHandler = Callable[[ServerRequestContext[LifespanResultT], _ParamsT], Awaitable[None]]
"""A registered notification handler: `(ctx, params) -> None`."""


@dataclass(frozen=True, slots=True)
class HandlerEntry(Generic[LifespanResultT]):
    """A registered handler and the params model to validate incoming params against.

    The handler's second-argument type is erased to `Any` in storage (each entry has
    a different concrete params type and `Callable` parameters are contravariant);
    `params_type` carries the precise type, correlated at registration time by
    `Server.add_request_handler`.
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
    """Default no-op lifespan: yields an empty context."""
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
        # Context-tier middleware: wraps every inbound request (including `initialize`)
        # with `(ctx, call_next)`; applied in `ServerRunner._on_request`. OpenTelemetry
        # ships on by default (no-op until an exporter is installed); drop it to opt out.
        # TODO(L54): provisional - signature and semantics change with the Context/middleware
        # rework (covariant `Context[L]`, outbound seam) before v2 final.
        self.middleware: list[ServerMiddleware[LifespanResultT]] = [OpenTelemetryMiddleware()]
        # SEP-2133 extension settings (identifier -> settings) for `ServerCapabilities.extensions`;
        # higher layers populate it, `get_capabilities` reads it when no explicit map is passed.
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
        """Register a request handler for `method`, replacing any existing one.

        `params_type` validates incoming params before the handler is invoked; it
        should subclass `RequestParams` so `_meta` parses uniformly. A message with
        no `params` member validates `{}`: required fields reject as INVALID_PARAMS,
        all-optional models reach the handler with their defaults - never `None`.
        `initialize` is reserved (the runner owns the handshake) and raises
        `ValueError`; use `Server.middleware` to observe or wrap initialization.
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
        """Register a notification handler for `method`, replacing any existing one.

        `params_type` should subclass `NotificationParams` so `_meta` parses
        uniformly; absent params validate `{}` as for requests, so the handler never
        receives `None`. A `notifications/initialized` handler runs after the runner
        has marked the connection initialized.
        """
        self._notification_handlers[method] = HandlerEntry(params_type, handler)

    def get_request_handler(self, method: str) -> HandlerEntry[LifespanResultT] | None:
        """Return the registered entry for a request method, or `None`."""
        return self._request_handlers.get(method)

    def get_notification_handler(self, method: str) -> HandlerEntry[LifespanResultT] | None:
        """Return the registered entry for a notification method, or `None`."""
        return self._notification_handlers.get(method)

    # TODO(L53): rethink capabilities API - derive capabilities entirely from server state
    # (e.g. constructor params for list_changed) instead of requiring callers to assemble
    # NotificationOptions/experimental_capabilities at create_initialization_options() time.
    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
    ) -> InitializationOptions:
        """Create initialization options from this server instance.

        `extensions` advertises SEP-2133 extension support (identifier -> settings)
        under `ServerCapabilities.extensions`; defaults to `self.extensions`.
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
    ) -> types.ServerCapabilities:
        """Convert existing handlers to a ServerCapabilities object.

        `extensions` is the SEP-2133 extension map (identifier -> settings);
        defaults to `self.extensions`.
        """
        notification_options = notification_options or NotificationOptions()
        prompts_capability = None
        resources_capability = None
        tools_capability = None
        logging_capability = None
        completions_capability = None

        if "prompts/list" in self._request_handlers:
            prompts_capability = types.PromptsCapability(list_changed=notification_options.prompts_changed)

        if "resources/list" in self._request_handlers:
            resources_capability = types.ResourcesCapability(
                subscribe="resources/subscribe" in self._request_handlers,
                list_changed=notification_options.resources_changed,
            )

        if "tools/list" in self._request_handlers:
            tools_capability = types.ToolsCapability(list_changed=notification_options.tools_changed)

        if "logging/setLevel" in self._request_handlers:
            logging_capability = types.LoggingCapability()

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

        `version` falls back to the installed `mcp` package version when not supplied.
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

        Capabilities derive from server state at call time; replace wholesale via
        `add_request_handler("server/discover", ...)`. Reachability for legacy
        peers is decided at the boundary (`types.methods`), not here.
        """
        return types.DiscoverResult(
            supported_versions=list(MODERN_PROTOCOL_VERSIONS),
            capabilities=self.get_capabilities(),
            server_info=self.server_info,
            instructions=self.instructions,
        )

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """The StreamableHTTP session manager.

        Raises:
            RuntimeError: If accessed before `streamable_http_app()` has created it.
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
        # True re-raises handler exceptions (shutting the server down) instead of
        # returning error responses - eases tracing in tests and in-process servers.
        raise_exceptions: bool = False,
    ) -> None:
        """Serve a single connection over the given streams until the read side closes.

        Thin wrapper over `serve_loop`: enters the server lifespan,
        then drives the loop. Transports with their own lifespan owner
        (the streamable-HTTP manager) call `serve_loop` directly instead.
        """
        async with self.lifespan(self) as lifespan_context:
            await serve_loop(
                self,
                read_stream,
                write_stream,
                lifespan_state=lifespan_context,
                init_options=initialization_options,
                raise_exceptions=raise_exceptions,
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

        streamable_http_app = StreamableHTTPASGIApp(session_manager)

        routes: list[Route | Mount] = []
        middleware: list[Middleware] = []
        required_scopes: list[str] = []

        if auth:
            required_scopes = auth.required_scopes or []

            if token_verifier:
                middleware = [
                    Middleware(
                        AuthenticationMiddleware,
                        backend=BearerAuthBackend(token_verifier),
                    ),
                    Middleware(AuthContextMiddleware),
                ]

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

        if token_verifier:
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
            routes.append(
                Route(
                    streamable_http_path,
                    endpoint=streamable_http_app,
                )
            )

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
