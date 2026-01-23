"""MCP Server Module

This module provides a framework for creating an MCP (Model Context Protocol) server.
It allows you to easily define and handle various types of requests and notifications
in an asynchronous manner.

Usage:
1. Create a Server instance:
   server = Server("your_server_name")

2. Define request handlers using decorators:
   @server.list_prompts()
   async def handle_list_prompts(request: types.ListPromptsRequest) -> types.ListPromptsResult:
       # Implementation

   @server.get_prompt()
   async def handle_get_prompt(
       name: str, arguments: dict[str, str] | None
   ) -> types.GetPromptResult:
       # Implementation

   @server.list_tools()
   async def handle_list_tools(request: types.ListToolsRequest) -> types.ListToolsResult:
       # Implementation

   @server.call_tool()
   async def handle_call_tool(
       name: str, arguments: dict | None
   ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
       # Implementation

   @server.list_resource_templates()
   async def handle_list_resource_templates() -> list[types.ResourceTemplate]:
       # Implementation

3. Define notification handlers if needed:
   @server.progress_notification()
   async def handle_progress(
       progress_token: str | int, progress: float, total: float | None,
       message: str | None
   ) -> None:
       # Implementation

4. Run the server:
   async def main():
       async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
           await server.run(
               read_stream,
               write_stream,
               InitializationOptions(
                   server_name="your_server_name",
                   server_version="your_version",
                   capabilities=server.get_capabilities(
                       notification_options=NotificationOptions(),
                       experimental_capabilities={},
                   ),
               ),
           )

   asyncio.run(main())

The Server class provides methods to register handlers for various MCP requests and
notifications. It automatically manages the request context and handles incoming
messages from the client.
"""

from __future__ import annotations

import base64
import contextvars
import json
import logging
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from importlib.metadata import version as importlib_version
from typing import Any, Generic, TypeAlias, cast

import anyio
import jsonschema
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Mount, Route
from typing_extensions import TypeVar

import mcp.types as types
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.experimental.request_context import Experimental
from mcp.server.lowlevel.experimental import ExperimentalHandlers
from mcp.server.lowlevel.func_inspection import create_call_wrapper
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError, UrlElicitationRequiredError
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.tool_name_validation import validate_and_warn_tool_name

logger = logging.getLogger(__name__)

LifespanResultT = TypeVar("LifespanResultT", default=Any)
RequestT = TypeVar("RequestT", default=Any)

# type aliases for tool call results
StructuredContent: TypeAlias = dict[str, Any]
UnstructuredContent: TypeAlias = Iterable[types.ContentBlock]
CombinationContent: TypeAlias = tuple[UnstructuredContent, StructuredContent]

# This will be properly typed in each Server instance's context
request_ctx: contextvars.ContextVar[RequestContext[ServerSession, Any, Any]] = contextvars.ContextVar("request_ctx")


class NotificationOptions:
    def __init__(
        self,
        prompts_changed: bool = False,
        resources_changed: bool = False,
        tools_changed: bool = False,
    ):
        self.prompts_changed = prompts_changed
        self.resources_changed = resources_changed
        self.tools_changed = tools_changed


@asynccontextmanager
async def lifespan(_: Server[LifespanResultT, RequestT]) -> AsyncIterator[dict[str, Any]]:
    """Default lifespan context manager that does nothing.

    Args:
        server: The server instance this lifespan is managing

    Returns:
        An empty context object
    """
    yield {}


class Server(Generic[LifespanResultT, RequestT]):
    def __init__(
        self,
        name: str,
        version: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[types.Icon] | None = None,
        lifespan: Callable[
            [Server[LifespanResultT, RequestT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
    ):
        self.name = name
        self.version = version
        self.title = title
        self.description = description
        self.instructions = instructions
        self.website_url = website_url
        self.icons = icons
        self.lifespan = lifespan
        self.request_handlers: dict[type, Callable[..., Awaitable[types.ServerResult]]] = {
            types.PingRequest: _ping_handler,
        }
        self.notification_handlers: dict[type, Callable[..., Awaitable[None]]] = {}
        self._tool_cache: dict[str, types.Tool] = {}
        self._experimental_handlers: ExperimentalHandlers | None = None
        self._session_manager: StreamableHTTPSessionManager | None = None
        logger.debug("Initializing server %r", name)

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
        if types.ListPromptsRequest in self.request_handlers:
            prompts_capability = types.PromptsCapability(list_changed=notification_options.prompts_changed)

        # Set resource capabilities if handler exists
        if types.ListResourcesRequest in self.request_handlers:
            resources_capability = types.ResourcesCapability(
                subscribe=False, list_changed=notification_options.resources_changed
            )

        # Set tool capabilities if handler exists
        if types.ListToolsRequest in self.request_handlers:
            tools_capability = types.ToolsCapability(list_changed=notification_options.tools_changed)

        # Set logging capabilities if handler exists
        if types.SetLevelRequest in self.request_handlers:  # pragma: no cover
            logging_capability = types.LoggingCapability()

        # Set completions capabilities if handler exists
        if types.CompleteRequest in self.request_handlers:
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
    def request_context(
        self,
    ) -> RequestContext[ServerSession, LifespanResultT, RequestT]:
        """If called outside of a request context, this will raise a LookupError."""
        return request_ctx.get()

    @property
    def experimental(self) -> ExperimentalHandlers:
        """Experimental APIs for tasks and other features.

        WARNING: These APIs are experimental and may change without notice.
        """

        # We create this inline so we only add these capabilities _if_ they're actually used
        if self._experimental_handlers is None:
            self._experimental_handlers = ExperimentalHandlers(self, self.request_handlers, self.notification_handlers)
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

    def list_prompts(self):
        def decorator(
            func: Callable[[], Awaitable[list[types.Prompt]]]
            | Callable[[types.ListPromptsRequest], Awaitable[types.ListPromptsResult]],
        ):
            logger.debug("Registering handler for PromptListRequest")

            wrapper = create_call_wrapper(func, types.ListPromptsRequest)

            async def handler(req: types.ListPromptsRequest):
                result = await wrapper(req)
                # Handle both old style (list[Prompt]) and new style (ListPromptsResult)
                if isinstance(result, types.ListPromptsResult):
                    return result
                else:
                    # Old style returns list[Prompt]
                    return types.ListPromptsResult(prompts=result)

            self.request_handlers[types.ListPromptsRequest] = handler
            return func

        return decorator

    def get_prompt(self):
        def decorator(
            func: Callable[[str, dict[str, str] | None], Awaitable[types.GetPromptResult]],
        ):
            logger.debug("Registering handler for GetPromptRequest")

            async def handler(req: types.GetPromptRequest):
                prompt_get = await func(req.params.name, req.params.arguments)
                return prompt_get

            self.request_handlers[types.GetPromptRequest] = handler
            return func

        return decorator

    def list_resources(self):
        def decorator(
            func: Callable[[], Awaitable[list[types.Resource]]]
            | Callable[[types.ListResourcesRequest], Awaitable[types.ListResourcesResult]],
        ):
            logger.debug("Registering handler for ListResourcesRequest")

            wrapper = create_call_wrapper(func, types.ListResourcesRequest)

            async def handler(req: types.ListResourcesRequest):
                result = await wrapper(req)
                # Handle both old style (list[Resource]) and new style (ListResourcesResult)
                if isinstance(result, types.ListResourcesResult):
                    return result
                else:
                    # Old style returns list[Resource]
                    return types.ListResourcesResult(resources=result)

            self.request_handlers[types.ListResourcesRequest] = handler
            return func

        return decorator

    def list_resource_templates(self):
        def decorator(func: Callable[[], Awaitable[list[types.ResourceTemplate]]]):
            logger.debug("Registering handler for ListResourceTemplatesRequest")

            async def handler(_: Any):
                templates = await func()
                return types.ListResourceTemplatesResult(resource_templates=templates)

            self.request_handlers[types.ListResourceTemplatesRequest] = handler
            return func

        return decorator

    def read_resource(self):
        def decorator(
            func: Callable[[str], Awaitable[str | bytes | Iterable[ReadResourceContents]]],
        ):
            logger.debug("Registering handler for ReadResourceRequest")

            async def handler(req: types.ReadResourceRequest):
                result = await func(req.params.uri)

                def create_content(data: str | bytes, mime_type: str | None, meta: dict[str, Any] | None = None):
                    # Note: ResourceContents uses Field(alias="_meta"), so we must use the alias key
                    meta_kwargs: dict[str, Any] = {"_meta": meta} if meta is not None else {}
                    match data:
                        case str() as data:
                            return types.TextResourceContents(
                                uri=req.params.uri,
                                text=data,
                                mime_type=mime_type or "text/plain",
                                **meta_kwargs,
                            )
                        case bytes() as data:  # pragma: no cover
                            return types.BlobResourceContents(
                                uri=req.params.uri,
                                blob=base64.b64encode(data).decode(),
                                mime_type=mime_type or "application/octet-stream",
                                **meta_kwargs,
                            )

                match result:
                    case str() | bytes() as data:  # pragma: no cover
                        warnings.warn(
                            "Returning str or bytes from read_resource is deprecated. "
                            "Use Iterable[ReadResourceContents] instead.",
                            DeprecationWarning,
                            stacklevel=2,
                        )
                        content = create_content(data, None)
                    case Iterable() as contents:
                        contents_list = [
                            create_content(
                                content_item.content, content_item.mime_type, getattr(content_item, "meta", None)
                            )
                            for content_item in contents
                        ]
                        return types.ReadResourceResult(contents=contents_list)
                    case _:  # pragma: no cover
                        raise ValueError(f"Unexpected return type from read_resource: {type(result)}")

                return types.ReadResourceResult(  # pragma: no cover
                    contents=[content],
                )

            self.request_handlers[types.ReadResourceRequest] = handler
            return func

        return decorator

    def set_logging_level(self):  # pragma: no cover
        def decorator(func: Callable[[types.LoggingLevel], Awaitable[None]]):
            logger.debug("Registering handler for SetLevelRequest")

            async def handler(req: types.SetLevelRequest):
                await func(req.params.level)
                return types.EmptyResult()

            self.request_handlers[types.SetLevelRequest] = handler
            return func

        return decorator

    def subscribe_resource(self):  # pragma: no cover
        def decorator(func: Callable[[str], Awaitable[None]]):
            logger.debug("Registering handler for SubscribeRequest")

            async def handler(req: types.SubscribeRequest):
                await func(req.params.uri)
                return types.EmptyResult()

            self.request_handlers[types.SubscribeRequest] = handler
            return func

        return decorator

    def unsubscribe_resource(self):  # pragma: no cover
        def decorator(func: Callable[[str], Awaitable[None]]):
            logger.debug("Registering handler for UnsubscribeRequest")

            async def handler(req: types.UnsubscribeRequest):
                await func(req.params.uri)
                return types.EmptyResult()

            self.request_handlers[types.UnsubscribeRequest] = handler
            return func

        return decorator

    def list_tools(self):
        def decorator(
            func: Callable[[], Awaitable[list[types.Tool]]]
            | Callable[[types.ListToolsRequest], Awaitable[types.ListToolsResult]],
        ):
            logger.debug("Registering handler for ListToolsRequest")

            wrapper = create_call_wrapper(func, types.ListToolsRequest)

            async def handler(req: types.ListToolsRequest):
                result = await wrapper(req)

                # Handle both old style (list[Tool]) and new style (ListToolsResult)
                if isinstance(result, types.ListToolsResult):  # pragma: no cover
                    # Refresh the tool cache with returned tools
                    for tool in result.tools:
                        validate_and_warn_tool_name(tool.name)
                        self._tool_cache[tool.name] = tool
                    return result
                else:
                    # Old style returns list[Tool]
                    # Clear and refresh the entire tool cache
                    self._tool_cache.clear()
                    for tool in result:
                        validate_and_warn_tool_name(tool.name)
                        self._tool_cache[tool.name] = tool
                    return types.ListToolsResult(tools=result)

            self.request_handlers[types.ListToolsRequest] = handler
            return func

        return decorator

    def _make_error_result(self, error_message: str) -> types.CallToolResult:
        """Create a CallToolResult with an error."""
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=error_message)],
            is_error=True,
        )

    async def _get_cached_tool_definition(self, tool_name: str) -> types.Tool | None:
        """Get tool definition from cache, refreshing if necessary.

        Returns the Tool object if found, None otherwise.
        """
        if tool_name not in self._tool_cache:
            if types.ListToolsRequest in self.request_handlers:
                logger.debug("Tool cache miss for %s, refreshing cache", tool_name)
                await self.request_handlers[types.ListToolsRequest](None)

        tool = self._tool_cache.get(tool_name)
        if tool is None:
            logger.warning("Tool '%s' not listed, no validation will be performed", tool_name)

        return tool

    def call_tool(self, *, validate_input: bool = True):
        """Register a tool call handler.

        Args:
            validate_input: If True, validates input against inputSchema. Default is True.

        The handler validates input against inputSchema (if validate_input=True), calls the tool function,
        and builds a CallToolResult with the results:
        - Unstructured content (iterable of ContentBlock): returned in content
        - Structured content (dict): returned in structuredContent, serialized JSON text returned in content
        - Both: returned in content and structuredContent

        If outputSchema is defined, validates structuredContent or errors if missing.
        """

        def decorator(
            func: Callable[
                [str, dict[str, Any]],
                Awaitable[
                    UnstructuredContent
                    | StructuredContent
                    | CombinationContent
                    | types.CallToolResult
                    | types.CreateTaskResult
                ],
            ],
        ):
            logger.debug("Registering handler for CallToolRequest")

            async def handler(req: types.CallToolRequest):
                try:
                    tool_name = req.params.name
                    arguments = req.params.arguments or {}
                    tool = await self._get_cached_tool_definition(tool_name)

                    # input validation
                    if validate_input and tool:
                        try:
                            jsonschema.validate(instance=arguments, schema=tool.input_schema)
                        except jsonschema.ValidationError as e:
                            return self._make_error_result(f"Input validation error: {e.message}")

                    # tool call
                    results = await func(tool_name, arguments)

                    # output normalization
                    unstructured_content: UnstructuredContent
                    maybe_structured_content: StructuredContent | None
                    if isinstance(results, types.CallToolResult):
                        return results
                    elif isinstance(results, types.CreateTaskResult):
                        # Task-augmented execution returns task info instead of result
                        return results
                    elif isinstance(results, tuple) and len(results) == 2:
                        # tool returned both structured and unstructured content
                        unstructured_content, maybe_structured_content = cast(CombinationContent, results)
                    elif isinstance(results, dict):
                        # tool returned structured content only
                        maybe_structured_content = cast(StructuredContent, results)
                        unstructured_content = [types.TextContent(type="text", text=json.dumps(results, indent=2))]
                    elif hasattr(results, "__iter__"):  # pragma: no cover
                        # tool returned unstructured content only
                        unstructured_content = cast(UnstructuredContent, results)
                        maybe_structured_content = None
                    else:  # pragma: no cover
                        return self._make_error_result(f"Unexpected return type from tool: {type(results).__name__}")

                    # output validation
                    if tool and tool.output_schema is not None:
                        if maybe_structured_content is None:
                            return self._make_error_result(
                                "Output validation error: outputSchema defined but no structured output returned"
                            )
                        else:
                            try:
                                jsonschema.validate(instance=maybe_structured_content, schema=tool.output_schema)
                            except jsonschema.ValidationError as e:
                                return self._make_error_result(f"Output validation error: {e.message}")

                    # result
                    return types.CallToolResult(
                        content=list(unstructured_content),
                        structured_content=maybe_structured_content,
                        is_error=False,
                    )
                except UrlElicitationRequiredError:
                    # Re-raise UrlElicitationRequiredError so it can be properly handled
                    # by _handle_request, which converts it to an error response with code -32042
                    raise
                except McpError:
                    # Re-raise McpError as protocol error
                    # (e.g., unknown tool returns INVALID_PARAMS per MCP spec)
                    raise
                except Exception as e:
                    return self._make_error_result(str(e))

            self.request_handlers[types.CallToolRequest] = handler
            return func

        return decorator

    def progress_notification(self):
        def decorator(
            func: Callable[[str | int, float, float | None, str | None], Awaitable[None]],
        ):
            logger.debug("Registering handler for ProgressNotification")

            async def handler(req: types.ProgressNotification):
                await func(
                    req.params.progress_token,
                    req.params.progress,
                    req.params.total,
                    req.params.message,
                )

            self.notification_handlers[types.ProgressNotification] = handler
            return func

        return decorator

    def completion(self):
        """Provides completions for prompts and resource templates"""

        def decorator(
            func: Callable[
                [
                    types.PromptReference | types.ResourceTemplateReference,
                    types.CompletionArgument,
                    types.CompletionContext | None,
                ],
                Awaitable[types.Completion | None],
            ],
        ):
            logger.debug("Registering handler for CompleteRequest")

            async def handler(req: types.CompleteRequest):
                completion = await func(req.params.ref, req.params.argument, req.params.context)
                return types.CompleteResult(
                    completion=completion
                    if completion is not None
                    else types.Completion(values=[], total=None, has_more=None),
                )

            self.request_handlers[types.CompleteRequest] = handler
            return func

        return decorator

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
                async for message in session.incoming_messages:
                    logger.debug("Received message: %s", message)

                    tg.start_soon(
                        self._handle_message,
                        message,
                        session,
                        lifespan_context,
                        raise_exceptions,
                    )

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
                case Exception():  # pragma: no cover
                    logger.error(f"Received exception from stream: {message}")
                    await session.send_log_message(
                        level="error",
                        data="Internal Server Error",
                        logger="mcp.server.exception_handler",
                    )
                    if raise_exceptions:
                        raise message
                case _:
                    await self._handle_notification(message)

            for warning in w:  # pragma: no cover
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

        if handler := self.request_handlers.get(type(req)):
            logger.debug("Dispatching request of type %s", type(req).__name__)

            token = None
            try:
                # Extract request context and close_sse_stream from message metadata
                request_data = None
                close_sse_stream_cb = None
                close_standalone_sse_stream_cb = None
                if message.message_metadata is not None and isinstance(
                    message.message_metadata, ServerMessageMetadata
                ):  # pragma: no cover
                    request_data = message.message_metadata.request_context
                    close_sse_stream_cb = message.message_metadata.close_sse_stream
                    close_standalone_sse_stream_cb = message.message_metadata.close_standalone_sse_stream

                # Set our global state that can be retrieved via
                # app.get_request_context()
                client_capabilities = session.client_params.capabilities if session.client_params else None
                task_support = self._experimental_handlers.task_support if self._experimental_handlers else None
                # Get task metadata from request params if present
                task_metadata = None
                if hasattr(req, "params") and req.params is not None:
                    task_metadata = getattr(req.params, "task", None)
                token = request_ctx.set(
                    RequestContext(
                        message.request_id,
                        message.request_meta,
                        session,
                        lifespan_context,
                        Experimental(
                            task_metadata=task_metadata,
                            _client_capabilities=client_capabilities,
                            _session=session,
                            _task_support=task_support,
                        ),
                        request=request_data,
                        close_sse_stream=close_sse_stream_cb,
                        close_standalone_sse_stream=close_standalone_sse_stream_cb,
                    )
                )
                response = await handler(req)
            except McpError as err:  # pragma: no cover
                response = err.error
            except anyio.get_cancelled_exc_class():  # pragma: no cover
                logger.info(
                    "Request %s cancelled - duplicate response suppressed",
                    message.request_id,
                )
                return
            except Exception as err:  # pragma: no cover
                if raise_exceptions:
                    raise err
                response = types.ErrorData(code=0, message=str(err), data=None)
            finally:
                # Reset the global state after we are done
                if token is not None:  # pragma: no branch
                    request_ctx.reset(token)

            await message.respond(response)
        else:  # pragma: no cover
            await message.respond(
                types.ErrorData(
                    code=types.METHOD_NOT_FOUND,
                    message="Method not found",
                )
            )

        logger.debug("Response sent")

    async def _handle_notification(self, notify: Any):
        if handler := self.notification_handlers.get(type(notify)):  # type: ignore
            logger.debug("Dispatching notification of type %s", type(notify).__name__)

            try:
                await handler(notify)
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
        auth_server_provider: (OAuthAuthorizationServerProvider[Any, Any, Any] | None) = None,
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


async def _ping_handler(request: types.PingRequest) -> types.ServerResult:
    return types.EmptyResult()
