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

import contextvars
import logging
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from importlib.metadata import version as importlib_version
from typing import TYPE_CHECKING, Any, Generic

if TYPE_CHECKING:
    from builtins import BaseExceptionGroup
else:
    try:
        from builtins import BaseExceptionGroup
    except ImportError:
        from exceptiongroup import BaseExceptionGroup

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount, Route
from typing_extensions import TypeVar

from mcp import types
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.context import ServerRequestContext
from mcp.server.experimental.request_context import Experimental
from mcp.server.lowlevel.experimental import ExperimentalHandlers
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder

logger = logging.getLogger(__name__)

LifespanResultT = TypeVar("LifespanResultT", default=Any)

request_ctx: contextvars.ContextVar[ServerRequestContext[Any]] = contextvars.ContextVar("request_ctx")


class NotificationOptions:
    def __init__(self, prompts_changed: bool = False, resources_changed: bool = False, tools_changed: bool = False):
        self.prompts_changed = prompts_changed
        self.resources_changed = resources_changed
        self.tools_changed = tools_changed


@asynccontextmanager
async def lifespan(_: Server[LifespanResultT]) -> AsyncIterator[dict[str, Any]]:
    """Default lifespan context manager that does nothing.

    Returns:
        An empty context object
    """
    yield {}


async def _ping_handler(ctx: ServerRequestContext[Any], params: types.RequestParams | None) -> types.EmptyResult:
    return types.EmptyResult()


class Server(Generic[LifespanResultT]):
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
            Awaitable[types.CallToolResult | types.CreateTaskResult],
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
            Awaitable[types.ReadResourceResult],
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
        on_list_prompts: Callable[
            [ServerRequestContext[LifespanResultT], types.PaginatedRequestParams | None],
            Awaitable[types.ListPromptsResult],
        ]
        | None = None,
        on_get_prompt: Callable[
            [ServerRequestContext[LifespanResultT], types.GetPromptRequestParams],
            Awaitable[types.GetPromptResult],
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
    ):
        self.name = name
        self.version = version
        self.title = title
        self.description = description
        self.instructions = instructions
        self.website_url = website_url
        self.icons = icons
        self.lifespan = lifespan
        self._request_handlers: dict[str, Callable[[ServerRequestContext[LifespanResultT], Any], Awaitable[Any]]] = {}
        self._notification_handlers: dict[
            str, Callable[[ServerRequestContext[LifespanResultT], Any], Awaitable[None]]
        ] = {}
        self._experimental_handlers: ExperimentalHandlers[LifespanResultT] | None = None
        self._session_manager: StreamableHTTPSessionManager | None = None
        logger.debug("Initializing server %r", name)

        # Populate internal handler dicts from on_* kwargs
        self._request_handlers.update(
            {
                method: handler
                for method, handler in {
                    "ping": on_ping,
                    "prompts/list": on_list_prompts,
                    "prompts/get": on_get_prompt,
                    "resources/list": on_list_resources,
                    "resources/templates/list": on_list_resource_templates,
                    "resources/read": on_read_resource,
                    "resources/subscribe": on_subscribe_resource,
                    "resources/unsubscribe": on_unsubscribe_resource,
                    "tools/list": on_list_tools,
                    "tools/call": on_call_tool,
                    "logging/setLevel": on_set_logging_level,
                    "completion/complete": on_completion,
                }.items()
                if handler is not None
            }
        )

        self._notification_handlers.update(
            {
                method: handler
                for method, handler in {
                    "notifications/roots/list_changed": on_roots_list_changed,
                    "notifications/progress": on_progress,
                }.items()
                if handler is not None
            }
        )

    def _add_request_handler(
        self,
        method: str,
        handler: Callable[[ServerRequestContext[LifespanResultT], Any], Awaitable[Any]],
    ) -> None:
        """Add a request handler, silently replacing any existing handler for the same method."""
        self._request_handlers[method] = handler

    def _has_handler(self, method: str) -> bool:
        """Check if a handler is registered for the given method."""
        return method in self._request_handlers or method in self._notification_handlers

    # TODO: Rethink capabilities API. Currently capabilities are derived from registered
    # handlers but require NotificationOptions to be passed externally for list_changed
    # flags, and experimental_capabilities as a separate dict. Consider deriving capabilities
    # entirely from server state (e.g. constructor params for list_changed) instead of
    # requiring callers to assemble them at create_initialization_options() time.
    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
    ) -> InitializationOptions:
        """Create initialization options from this server instance."""

        def pkg_version(package: str) -> str:
            try:
                return importlib_version(package)
            except Exception:  # pragma: no cover
                pass

            return "unknown"  # pragma: no cover

        return InitializationOptions(
            server_name=self.name,
            server_version=self.version if self.version else pkg_version("mcp"),
            title=self.title,
            description=self.description,
            capabilities=self.get_capabilities(
                notification_options or NotificationOptions(),
                experimental_capabilities or {},
            ),
            instructions=self.instructions,
            website_url=self.website_url,
            icons=self.icons,
        )

    def get_capabilities(
        self,
        notification_options: NotificationOptions,
        experimental_capabilities: dict[str, dict[str, Any]],
    ) -> types.ServerCapabilities:
        """Convert existing handlers to a ServerCapabilities object."""
        prompts_capability = None
        resources_capability = None
        tools_capability = None
        logging_capability = None
        completions_capability = None

        # Set prompt capabilities if handler exists
        if "prompts/list" in self._request_handlers:
            prompts_capability = types.PromptsCapability(list_changed=notification_options.prompts_changed)

        # Set resource capabilities if handler exists
        if "resources/list" in self._request_handlers:
            resources_capability = types.ResourcesCapability(
                subscribe="resources/subscribe" in self._request_handlers,
                list_changed=notification_options.resources_changed,
            )

        # Set tool capabilities if handler exists
        if "tools/list" in self._request_handlers:
            tools_capability = types.ToolsCapability(list_changed=notification_options.tools_changed)

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
            completions=completions_capability,
        )
        if self._experimental_handlers:
            self._experimental_handlers.update_capabilities(capabilities)
        return capabilities

    @property
    def experimental(self) -> ExperimentalHandlers[LifespanResultT]:
        """Experimental APIs for tasks and other features.

        WARNING: These APIs are experimental and may change without notice.
        """

        # We create this inline so we only add these capabilities _if_ they're actually used
        if self._experimental_handlers is None:
            self._experimental_handlers = ExperimentalHandlers(
                add_request_handler=self._add_request_handler,
                has_handler=self._has_handler,
            )
        return self._experimental_handlers

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """Get the StreamableHTTP session manager.

        Raises:
            RuntimeError: If called before streamable_http_app() has been called.
        """
        if self._session_manager is None:  # pragma: no cover
            raise RuntimeError(
                "Session manager can only be accessed after calling streamable_http_app(). "
                "The session manager is created lazily to avoid unnecessary initialization."
            )
        return self._session_manager  # pragma: no cover

    async def run(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
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
    ):
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(self.lifespan(self))
            session = await stack.enter_async_context(
                ServerSession(
                    read_stream,
                    write_stream,
                    initialization_options,
                    stateless=stateless,
                )
            )

            # Configure task support for this session if enabled
            task_support = self._experimental_handlers.task_support if self._experimental_handlers else None
            if task_support is not None:
                task_support.configure_session(session)
                await stack.enter_async_context(task_support.run())

            async with anyio.create_task_group() as tg:
                try:
                    async for message in session.incoming_messages:
                        logger.debug("Received message: %s", message)

                        tg.start_soon(
                            self._handle_message,
                            message,
                            session,
                            lifespan_context,
                            raise_exceptions,
                        )
                except BaseExceptionGroup as e:
                    from mcp.shared.exceptions import unwrap_task_group_exception

                    real_exc = unwrap_task_group_exception(e)
                    if real_exc is not e:
                        raise real_exc

    async def _handle_message(
        self,
        message: RequestResponder[types.ClientRequest, types.ServerResult] | types.ClientNotification | Exception,
        session: ServerSession,
        lifespan_context: LifespanResultT,
        raise_exceptions: bool = False,
    ):
        with warnings.catch_warnings(record=True) as w:
            match message:
                case RequestResponder() as responder:
                    with responder:
                        await self._handle_request(
                            message, responder.request, session, lifespan_context, raise_exceptions
                        )
                case Exception():
                    logger.error(f"Received exception from stream: {message}")
                    await session.send_log_message(
                        level="error",
                        data="Internal Server Error",
                        logger="mcp.server.exception_handler",
                    )
                    if raise_exceptions:
                        raise message
                case _:
                    await self._handle_notification(message, session, lifespan_context)

            for warning in w:  # pragma: lax no cover
                logger.info("Warning: %s: %s", warning.category.__name__, warning.message)

    async def _handle_request(
        self,
        message: RequestResponder[types.ClientRequest, types.ServerResult],
        req: types.ClientRequest,
        session: ServerSession,
        lifespan_context: LifespanResultT,
        raise_exceptions: bool,
    ):
        logger.info("Processing request of type %s", type(req).__name__)

        if handler := self._request_handlers.get(req.method):
            logger.debug("Dispatching request of type %s", type(req).__name__)

            try:
                # Extract request context and close_sse_stream from message metadata
                request_data = None
                close_sse_stream_cb = None
                close_standalone_sse_stream_cb = None
                if message.message_metadata is not None and isinstance(message.message_metadata, ServerMessageMetadata):
                    request_data = message.message_metadata.request_context
                    close_sse_stream_cb = message.message_metadata.close_sse_stream
                    close_standalone_sse_stream_cb = message.message_metadata.close_standalone_sse_stream

                client_capabilities = session.client_params.capabilities if session.client_params else None
                task_support = self._experimental_handlers.task_support if self._experimental_handlers else None
                # Get task metadata from request params if present
                task_metadata = None
                if hasattr(req, "params") and req.params is not None:
                    task_metadata = getattr(req.params, "task", None)
                ctx = ServerRequestContext(
                    request_id=message.request_id,
                    meta=message.request_meta,
                    session=session,
                    lifespan_context=lifespan_context,
                    experimental=Experimental(
                        task_metadata=task_metadata,
                        _client_capabilities=client_capabilities,
                        _session=session,
                        _task_support=task_support,
                    ),
                    request=request_data,
                    close_sse_stream=close_sse_stream_cb,
                    close_standalone_sse_stream=close_standalone_sse_stream_cb,
                )
                token = request_ctx.set(ctx)
                try:
                    response = await handler(ctx, req.params)
                finally:
                    request_ctx.reset(token)
            except MCPError as err:
                response = err.error
            except anyio.get_cancelled_exc_class():
                logger.info("Request %s cancelled - duplicate response suppressed", message.request_id)
                return
            except Exception as err:
                if raise_exceptions:  # pragma: no cover
                    raise err
                response = types.ErrorData(code=0, message=str(err))

            await message.respond(response)
        else:  # pragma: no cover
            await message.respond(types.ErrorData(code=types.METHOD_NOT_FOUND, message="Method not found"))

        logger.debug("Response sent")

    async def _handle_notification(
        self,
        notify: types.ClientNotification,
        session: ServerSession,
        lifespan_context: LifespanResultT,
    ) -> None:
        if handler := self._notification_handlers.get(notify.method):
            logger.debug("Dispatching notification of type %s", type(notify).__name__)

            try:
                client_capabilities = session.client_params.capabilities if session.client_params else None
                task_support = self._experimental_handlers.task_support if self._experimental_handlers else None
                ctx = ServerRequestContext(
                    session=session,
                    lifespan_context=lifespan_context,
                    experimental=Experimental(
                        task_metadata=None,
                        _client_capabilities=client_capabilities,
                        _session=session,
                        _task_support=task_support,
                    ),
                )
                await handler(ctx, notify.params)
            except Exception:  # pragma: no cover
                logger.exception("Uncaught exception in notification handler")

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
        if auth:  # pragma: no cover
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
                    )
                )

        # Set up routes with or without auth
        if token_verifier:  # pragma: no cover
            # Determine resource metadata URL
            resource_metadata_url = None
            if auth and auth.resource_server_url:
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
        if auth and auth.resource_server_url:  # pragma: no cover
            routes.extend(
                create_protected_resource_routes(
                    resource_url=auth.resource_server_url,
                    authorization_servers=[auth.issuer_url],
                    scopes_supported=auth.required_scopes,
                )
            )

        if custom_starlette_routes:  # pragma: no cover
            routes.extend(custom_starlette_routes)

        return Starlette(
            debug=debug,
            routes=routes,
            middleware=middleware,
            lifespan=lambda app: session_manager.run(),
        )
