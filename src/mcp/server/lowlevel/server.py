"""
MCP Server Module

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

from __future__ import annotations as _annotations

import contextvars
import json
import logging
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, cast

import anyio
import jsonschema
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl
from typing_extensions import TypeVar

import mcp.types as types
from mcp.server.lowlevel.func_inspection import create_call_wrapper
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.async_operations_utils import ServerAsyncOperation, ToolExecutorParameters
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import NEXT_PROTOCOL_VERSION, Operation, RequestId

if TYPE_CHECKING:
    from mcp.shared.async_operations import ServerAsyncOperationManager

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
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[types.Icon] | None = None,
        async_operations: ServerAsyncOperationManager | None = None,
        lifespan: Callable[
            [Server[LifespanResultT, RequestT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
    ):
        from mcp.shared.async_operations import ServerAsyncOperationManager

        self.name = name
        self.version = version
        self.instructions = instructions
        self.website_url = website_url
        self.icons = icons
        self.lifespan = lifespan
        self.async_operations = async_operations or ServerAsyncOperationManager()
        self.async_operations.set_handler(self._execute_tool_async)
        # Track request ID to operation token mapping for cancellation
        self._request_to_operation: dict[RequestId, str] = {}
        # Store tool functions for async execution
        self._tool_function: (
            Callable[..., Awaitable[UnstructuredContent | StructuredContent | CombinationContent]] | None
        ) = None
        self.request_handlers: dict[type, Callable[..., Awaitable[types.ServerResult]]] = {
            types.PingRequest: _ping_handler,
        }
        self.notification_handlers: dict[type, Callable[..., Awaitable[None]]] = {
            types.CancelledNotification: self._handle_cancelled_notification,
        }
        self._tool_cache: dict[str, types.Tool] = {}
        logger.debug("Initializing server %r", name)

    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
    ) -> InitializationOptions:
        """Create initialization options from this server instance."""

        def pkg_version(package: str) -> str:
            try:
                from importlib.metadata import version

                return version(package)
            except Exception:
                pass

            return "unknown"

        return InitializationOptions(
            server_name=self.name,
            server_version=self.version if self.version else pkg_version("mcp"),
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
            prompts_capability = types.PromptsCapability(listChanged=notification_options.prompts_changed)

        # Set resource capabilities if handler exists
        if types.ListResourcesRequest in self.request_handlers:
            resources_capability = types.ResourcesCapability(
                subscribe=False, listChanged=notification_options.resources_changed
            )

        # Set tool capabilities if handler exists
        if types.ListToolsRequest in self.request_handlers:
            tools_capability = types.ToolsCapability(listChanged=notification_options.tools_changed)

        # Set logging capabilities if handler exists
        if types.SetLevelRequest in self.request_handlers:
            logging_capability = types.LoggingCapability()

        # Set completions capabilities if handler exists
        if types.CompleteRequest in self.request_handlers:
            completions_capability = types.CompletionsCapability()

        return types.ServerCapabilities(
            prompts=prompts_capability,
            resources=resources_capability,
            tools=tools_capability,
            logging=logging_capability,
            experimental=experimental_capabilities,
            completions=completions_capability,
        )

    @property
    def request_context(
        self,
    ) -> RequestContext[ServerSession, LifespanResultT, RequestT]:
        """If called outside of a request context, this will raise a LookupError."""
        return request_ctx.get()

    def list_prompts(self):
        def decorator(
            func: Callable[[], Awaitable[list[types.Prompt]]]
            | Callable[[types.ListPromptsRequest], Awaitable[types.ListPromptsResult]],
        ):
            logger.debug("Registering handler for PromptListRequest")

            wrapper = create_call_wrapper(func, types.ListPromptsRequest)

            async def handler(req: types.ListPromptsRequest, _: Any = None):
                result = await wrapper(req)
                # Handle both old style (list[Prompt]) and new style (ListPromptsResult)
                if isinstance(result, types.ListPromptsResult):
                    return types.ServerResult(result)
                else:
                    # Old style returns list[Prompt]
                    return types.ServerResult(types.ListPromptsResult(prompts=result))

            self.request_handlers[types.ListPromptsRequest] = handler
            return func

        return decorator

    def get_prompt(self):
        def decorator(
            func: Callable[[str, dict[str, str] | None], Awaitable[types.GetPromptResult]],
        ):
            logger.debug("Registering handler for GetPromptRequest")

            async def handler(req: types.GetPromptRequest, _: Any = None):
                prompt_get = await func(req.params.name, req.params.arguments)
                return types.ServerResult(prompt_get)

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

            async def handler(req: types.ListResourcesRequest, _: Any = None):
                result = await wrapper(req)
                # Handle both old style (list[Resource]) and new style (ListResourcesResult)
                if isinstance(result, types.ListResourcesResult):
                    return types.ServerResult(result)
                else:
                    # Old style returns list[Resource]
                    return types.ServerResult(types.ListResourcesResult(resources=result))

            self.request_handlers[types.ListResourcesRequest] = handler
            return func

        return decorator

    def list_resource_templates(self):
        def decorator(func: Callable[[], Awaitable[list[types.ResourceTemplate]]]):
            logger.debug("Registering handler for ListResourceTemplatesRequest")

            async def handler(_1: Any, _2: Any = None):
                templates = await func()
                return types.ServerResult(types.ListResourceTemplatesResult(resourceTemplates=templates))

            self.request_handlers[types.ListResourceTemplatesRequest] = handler
            return func

        return decorator

    def read_resource(self):
        def decorator(
            func: Callable[[AnyUrl], Awaitable[str | bytes | Iterable[ReadResourceContents]]],
        ):
            logger.debug("Registering handler for ReadResourceRequest")

            async def handler(req: types.ReadResourceRequest, _: Any = None):
                result = await func(req.params.uri)

                def create_content(data: str | bytes, mime_type: str | None):
                    match data:
                        case str() as data:
                            return types.TextResourceContents(
                                uri=req.params.uri,
                                text=data,
                                mimeType=mime_type or "text/plain",
                            )
                        case bytes() as data:
                            import base64

                            return types.BlobResourceContents(
                                uri=req.params.uri,
                                blob=base64.b64encode(data).decode(),
                                mimeType=mime_type or "application/octet-stream",
                            )

                match result:
                    case str() | bytes() as data:
                        warnings.warn(
                            "Returning str or bytes from read_resource is deprecated. "
                            "Use Iterable[ReadResourceContents] instead.",
                            DeprecationWarning,
                            stacklevel=2,
                        )
                        content = create_content(data, None)
                    case Iterable() as contents:
                        contents_list = [
                            create_content(content_item.content, content_item.mime_type) for content_item in contents
                        ]
                        return types.ServerResult(
                            types.ReadResourceResult(
                                contents=contents_list,
                            )
                        )
                    case _:
                        raise ValueError(f"Unexpected return type from read_resource: {type(result)}")

                return types.ServerResult(
                    types.ReadResourceResult(
                        contents=[content],
                    )
                )

            self.request_handlers[types.ReadResourceRequest] = handler
            return func

        return decorator

    def set_logging_level(self):
        def decorator(func: Callable[[types.LoggingLevel], Awaitable[None]]):
            logger.debug("Registering handler for SetLevelRequest")

            async def handler(req: types.SetLevelRequest, _: Any = None):
                await func(req.params.level)
                return types.ServerResult(types.EmptyResult())

            self.request_handlers[types.SetLevelRequest] = handler
            return func

        return decorator

    def subscribe_resource(self):
        def decorator(func: Callable[[AnyUrl], Awaitable[None]]):
            logger.debug("Registering handler for SubscribeRequest")

            async def handler(req: types.SubscribeRequest, _: Any = None):
                await func(req.params.uri)
                return types.ServerResult(types.EmptyResult())

            self.request_handlers[types.SubscribeRequest] = handler
            return func

        return decorator

    def unsubscribe_resource(self):
        def decorator(func: Callable[[AnyUrl], Awaitable[None]]):
            logger.debug("Registering handler for UnsubscribeRequest")

            async def handler(req: types.UnsubscribeRequest, _: Any = None):
                await func(req.params.uri)
                return types.ServerResult(types.EmptyResult())

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

            async def handler(req: types.ListToolsRequest, _: Any = None):
                result = await wrapper(req)

                # Handle both old style (list[Tool]) and new style (ListToolsResult)
                if isinstance(result, types.ListToolsResult):
                    # Refresh the tool cache with returned tools
                    for tool in result.tools:
                        self._tool_cache[tool.name] = tool
                    return types.ServerResult(result)
                else:
                    # Old style returns list[Tool]
                    # Clear and refresh the entire tool cache
                    self._tool_cache.clear()
                    for tool in result:
                        self._tool_cache[tool.name] = tool
                    return types.ServerResult(types.ListToolsResult(tools=result))

            self.request_handlers[types.ListToolsRequest] = handler
            return func

        return decorator

    def _make_error_result(self, error_message: str) -> types.ServerResult:
        """Create a ServerResult with an error CallToolResult."""
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text=error_message)],
                isError=True,
            )
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
                ...,
                Awaitable[UnstructuredContent | StructuredContent | CombinationContent],
            ],
        ):
            logger.debug("Registering handler for CallToolRequest")

            # Store the tool function for async execution
            self._tool_function = func

            async def handler(req: types.CallToolRequest, server_scope: TaskGroup):
                try:
                    tool_name = req.params.name
                    arguments = req.params.arguments or {}
                    tool = await self._get_cached_tool_definition(tool_name)

                    # input validation
                    if validate_input and tool:
                        try:
                            jsonschema.validate(instance=arguments, schema=tool.inputSchema)
                        except jsonschema.ValidationError as e:
                            return self._make_error_result(f"Input validation error: {e.message}")

                    # Check for async execution
                    if tool and self.async_operations and self._should_execute_async(tool):
                        keep_alive = self._get_tool_keep_alive(tool)
                        immediate_content: list[types.ContentBlock] = []

                        # Execute immediate result if available
                        if self._has_immediate_result(tool):
                            try:
                                immediate_content = await self._execute_immediate_result(tool, arguments)
                                logger.debug(f"Executed immediate result for {tool_name}")
                            except McpError:
                                # Re-raise McpError as-is
                                raise
                            except Exception as e:
                                raise McpError(
                                    types.ErrorData(
                                        code=types.INTERNAL_ERROR,
                                        message=f"Immediate result execution failed: {str(e)}",
                                    )
                                )

                        # Create async operation
                        operation = await self.async_operations.create_operation(
                            tool_name=tool_name,
                            arguments=arguments,
                            keep_alive=keep_alive,
                        )
                        logger.debug(f"Created async operation with token: {operation.token}")

                        # Add the operation token to the request context
                        ctx = RequestContext(
                            request_id=self.request_context.request_id,
                            operation_token=self.request_context.operation_token,
                            meta=self.request_context.meta,
                            session=self.request_context.session,
                            supports_async=self._client_supports_async(self.request_context.session),
                            lifespan_context=self.request_context.lifespan_context,
                            request=self.request_context.request,
                        )
                        ctx.operation_token = operation.token
                        request_ctx.set(ctx)

                        # Start task with tool name and arguments
                        current_request_context = request_ctx.get()
                        await self.async_operations.start_task(
                            operation.token, tool_name, arguments, current_request_context
                        )

                        # Return operation result with immediate content
                        logger.info(f"Returning async operation result for {tool_name}")
                        return types.ServerResult(
                            types.CallToolResult(
                                content=immediate_content,
                                operation=types.AsyncResultProperties(
                                    token=operation.token,
                                    keepAlive=operation.keep_alive,
                                ),
                            )
                        )

                    # tool call
                    results = await func(tool_name, arguments)

                    # Process results using shared logic
                    try:
                        result = self._process_tool_result(results, tool)
                        return types.ServerResult(result)
                    except ValueError as e:
                        return self._make_error_result(str(e))
                except Exception as e:
                    return self._make_error_result(str(e))

            self.request_handlers[types.CallToolRequest] = handler
            return func

        return decorator

    def _client_supports_async(self, session: ServerSession) -> bool:
        """Check if the provided session supports async tools based on protocol version."""
        if session.client_params:
            client_version = str(session.client_params.protocolVersion)
            # Only "next" version supports async tools for now
            return client_version == NEXT_PROTOCOL_VERSION
        return False

    def _process_tool_result(
        self, results: UnstructuredContent | StructuredContent | CombinationContent, tool: types.Tool | None = None
    ) -> types.CallToolResult:
        """Process tool results and create CallToolResult with validation."""
        # output normalization
        unstructured_content: UnstructuredContent
        maybe_structured_content: StructuredContent | None
        if isinstance(results, tuple) and len(results) == 2:
            # tool returned both structured and unstructured content
            unstructured_content, maybe_structured_content = cast(CombinationContent, results)
        elif isinstance(results, dict):
            # tool returned structured content only
            maybe_structured_content = cast(StructuredContent, results)
            unstructured_content = [types.TextContent(type="text", text=json.dumps(results, indent=2))]
        elif hasattr(results, "__iter__"):
            # tool returned unstructured content only
            unstructured_content = cast(UnstructuredContent, results)
            maybe_structured_content = None
        else:
            raise ValueError(f"Unexpected return type from tool: {type(results).__name__}")

        # output validation
        if tool and tool.outputSchema is not None:
            if maybe_structured_content is None:
                raise ValueError("Output validation error: outputSchema defined but no structured output returned")
            else:
                try:
                    jsonschema.validate(instance=maybe_structured_content, schema=tool.outputSchema)
                except jsonschema.ValidationError as e:
                    raise ValueError(f"Output validation error: {e.message}")

        # result
        return types.CallToolResult(
            content=list(unstructured_content),
            structuredContent=maybe_structured_content,
            isError=False,
            _operation=Operation(token=self.request_context.operation_token)
            if self.request_context and self.request_context.operation_token
            else None,
        )

    def _should_execute_async(self, tool: types.Tool) -> bool:
        """Check if a tool should be executed asynchronously."""
        # Check if client supports async tools (protocol version "next")
        try:
            if self.request_context and self.request_context.session.client_params:
                client_version = str(self.request_context.session.client_params.protocolVersion)
                if client_version != "next":
                    return False
            else:
                return False
        except (AttributeError, ValueError):
            return False

        # Check if tool is async-only
        invocation_mode = getattr(tool, "invocationMode", None)
        return invocation_mode == "async"

    def _get_tool_keep_alive(self, tool: types.Tool) -> int:
        """Get the keepalive value for an async tool."""
        if tool.internal.keepalive is None:
            raise ValueError(f"keepalive not defined for tool {tool.name}")
        return tool.internal.keepalive

    def _has_immediate_result(self, tool: types.Tool) -> bool:
        """Check if tool has immediate_result function."""
        return tool.internal.immediate_result is not None and callable(tool.internal.immediate_result)

    async def _execute_immediate_result(self, tool: types.Tool, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        """Execute immediate result function and return content blocks."""
        immediate_fn = tool.internal.immediate_result

        if immediate_fn is None:
            raise ValueError(f"No immediate_result function found for tool {tool.name}")

        # Validate function signature and execute
        try:
            result = await immediate_fn(**arguments)
            if not isinstance(result, list):
                raise ValueError("immediate_result must return list[ContentBlock]")
            return cast(list[types.ContentBlock], result)
        except McpError:
            # Re-raise McpError as-is
            raise
        except Exception as e:
            raise McpError(
                types.ErrorData(code=types.INTERNAL_ERROR, message=f"Immediate result execution error: {str(e)}")
            )

    async def _execute_tool_async(self, params: ToolExecutorParameters) -> types.CallToolResult:
        """Execute a tool asynchronously and return the result."""
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(self.lifespan(self))
            session = await stack.enter_async_context(
                ServerSession(
                    params.server_read,
                    params.server_write,
                    self.create_initialization_options(),
                    stateless=True,  # Treat as initialized
                )
            )

            # Hydrate the request context
            context_token = None
            request_context = RequestContext(
                request_id=params.request_context.request_id,
                operation_token=params.request_context.operation_token,
                meta=params.request_context.meta,
                supports_async=params.request_context.supports_async,
                lifespan_context=lifespan_context,
                session=session,
            )

            try:
                # Restore the request context for this task
                if request_context:
                    context_token = request_ctx.set(request_context)

                logger.info(f"Starting async execution of tool '{params.tool_name}'")

                if not self._tool_function:
                    raise ValueError("No tool function registered")

                # Execute the tool function
                results = await self._tool_function(params.tool_name, params.arguments)

                # Get tool definition for validation
                tool = await self._get_cached_tool_definition(params.tool_name)

                # Process results using shared logic
                result = self._process_tool_result(results, tool)
                logger.info(f"Async execution of tool '{params.tool_name}' completed")
                return result
            finally:
                if context_token:
                    request_ctx.reset(context_token)

    def progress_notification(self):
        def decorator(
            func: Callable[[str | int, float, float | None, str | None], Awaitable[None]],
        ):
            logger.debug("Registering handler for ProgressNotification")

            async def handler(req: types.ProgressNotification, _: Any = None):
                await func(
                    req.params.progressToken,
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

            async def handler(req: types.CompleteRequest, _: Any = None):
                completion = await func(req.params.ref, req.params.argument, req.params.context)
                return types.ServerResult(
                    types.CompleteResult(
                        completion=completion
                        if completion is not None
                        else types.Completion(values=[], total=None, hasMore=None),
                    )
                )

            self.request_handlers[types.CompleteRequest] = handler
            return func

        return decorator

    async def _validate_operation_token(self, token: str) -> ServerAsyncOperation:
        """Validate operation token and return operation if valid."""
        operation = await self.async_operations.get_operation(token)
        if not operation:
            raise McpError(types.ErrorData(code=-32602, message="Invalid token"))

        if operation.is_expired:
            raise McpError(types.ErrorData(code=-32602, message="Token expired"))

        # Check if operation was cancelled - ignore subsequent requests
        if operation.status == "canceled":
            raise McpError(types.ErrorData(code=-32602, message="Operation was cancelled"))

        return operation

    def get_operation_status(self):
        """Register a handler for checking async tool execution status."""

        def decorator(func: Callable[[str], Awaitable[types.GetOperationStatusResult]]):
            logger.debug("Registering handler for GetOperationStatusRequest")

            async def handler(req: types.GetOperationStatusRequest, _: Any = None):
                # Validate token and get operation
                operation = await self._validate_operation_token(req.params.token)

                # Dequeue and send any pending events for this operation
                operation_request_queue = self.async_operations.operation_request_queue
                operation_response_queue = self.async_operations.operation_response_queue
                queued_messages = await operation_request_queue.dequeue_events(req.params.token)
                if queued_messages:
                    logger.debug(f"Dequeued {len(queued_messages)} events for operation {req.params.token}")
                    # Send queued messages to client using session methods
                    current_context = request_ctx.get()
                    if current_context and current_context.session:
                        for message in queued_messages:
                            try:
                                if isinstance(message.root, types.JSONRPCRequest):
                                    logger.debug(f"Received detached request: {message}")
                                    request_id = message.root.id
                                    validated_request = types.ServerRequest.model_validate(
                                        message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                                    )
                                    response = await current_context.session.send_request(
                                        validated_request, types.ClientResult
                                    )

                                    # Enqueue response back to response queue for detached session
                                    await operation_response_queue.enqueue_event(
                                        req.params.token,
                                        types.JSONRPCMessage(
                                            types.JSONRPCResponse(
                                                jsonrpc="2.0",
                                                id=request_id,
                                                result=response.model_dump(
                                                    by_alias=True, mode="json", exclude_none=True
                                                ),
                                            )
                                        ),
                                    )
                                elif isinstance(message.root, types.JSONRPCNotification):
                                    logger.debug(f"Received detached notification: {message}")
                                    validated_notification = types.ServerNotification.model_validate(
                                        message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                                    )
                                    await current_context.session.send_notification(validated_notification)
                                else:
                                    logger.debug(f"Invalid message in request queue: {message}")
                                    raise McpError(
                                        types.ErrorData(code=-32600, message="Invalid message type in event queue")
                                    )
                            except Exception:
                                logger.exception(f"Failed to process message: {message}")

                return types.ServerResult(
                    types.GetOperationStatusResult(
                        status=operation.status,
                        error=operation.error,
                    )
                )

            self.request_handlers[types.GetOperationStatusRequest] = handler
            return func

        return decorator

    def get_operation_result(self):
        """Register a handler for retrieving async tool execution results."""

        def decorator(func: Callable[[str], Awaitable[types.GetOperationPayloadResult]]):
            logger.debug("Registering handler for GetOperationPayloadRequest")

            async def handler(req: types.GetOperationPayloadRequest, _: Any = None):
                # Validate token and get operation
                operation = await self._validate_operation_token(req.params.token)

                if operation.status != "completed":
                    raise McpError(
                        types.ErrorData(code=-32600, message=f"Operation not completed (status: {operation.status})")
                    )

                if not operation.result:
                    raise McpError(types.ErrorData(code=-32600, message="No result available for completed operation"))

                return types.ServerResult(types.GetOperationPayloadResult(result=operation.result))

            self.request_handlers[types.GetOperationPayloadRequest] = handler
            return func

        return decorator

    async def handle_cancelled_notification(self, request_id: RequestId) -> None:
        """Handle cancellation notification for a request."""
        # Check if this request ID corresponds to an async operation
        if request_id in self._request_to_operation:
            token = self._request_to_operation[request_id]
            # Cancel the operation
            if await self.async_operations.cancel_operation(token):
                logger.debug(f"Cancelled async operation {token} for request {request_id}")
            # Clean up the mapping
            del self._request_to_operation[request_id]

    async def _handle_cancelled_notification(self, notification: types.CancelledNotification) -> None:
        """Handle cancelled notification from client."""
        request_id = notification.params.requestId
        logger.debug(f"Received cancellation notification for request {request_id}")
        await self.handle_cancelled_notification(request_id)

    async def send_request_for_operation(self, token: str, request: types.ServerRequest) -> None:
        """Send a request associated with an async operation."""
        # Mark operation as requiring input
        if await self.async_operations.mark_input_required(token):
            # Add operation token to request
            if hasattr(request.root, "params") and request.root.params is not None:
                if not hasattr(request.root.params, "operation") or request.root.params.operation is None:
                    request.root.params.operation = Operation(token=token)
            logger.debug(f"Marked operation {token} as input_required and added to request")

    async def send_notification_for_operation(self, token: str, notification: types.ServerNotification) -> None:
        """Send a notification associated with an async operation."""
        # Mark operation as requiring input
        if await self.async_operations.mark_input_required(token):
            # Add operation token to notification
            if hasattr(notification.root, "params") and notification.root.params is not None:
                if not hasattr(notification.root.params, "operation") or notification.root.params.operation is None:
                    notification.root.params.operation = Operation(token=token)
            logger.debug(f"Marked operation {token} as input_required and added to notification")

    async def complete_request_for_operation(self, token: str) -> None:
        """Mark that a request for an operation has been completed."""
        if await self.async_operations.mark_input_completed(token):
            logger.debug(f"Marked operation {token} as no longer requiring input")

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

            async with anyio.create_task_group() as tg:
                async for message in session.incoming_messages:
                    logger.debug("Received message: %s", message)

                    tg.start_soon(
                        self._handle_message,
                        message,
                        session,
                        lifespan_context,
                        raise_exceptions,
                        tg,
                    )

    async def _handle_message(
        self,
        message: RequestResponder[types.ClientRequest, types.ServerResult] | types.ClientNotification | Exception,
        session: ServerSession,
        lifespan_context: LifespanResultT,
        raise_exceptions: bool = False,
        server_scope: TaskGroup | None = None,
    ):
        with warnings.catch_warnings(record=True) as w:
            match message:
                case RequestResponder(request=types.ClientRequest(root=req)) as responder:
                    with responder:
                        await self._handle_request(
                            message, req, session, lifespan_context, raise_exceptions, server_scope
                        )
                case types.ClientNotification(root=notify):
                    await self._handle_notification(notify)
                case Exception():
                    logger.error(f"Received exception from stream: {message}")
                    await session.send_log_message(
                        level="error",
                        data="Internal Server Error",
                        logger="mcp.server.exception_handler",
                    )
                    if raise_exceptions:
                        raise message

            for warning in w:
                logger.info("Warning: %s: %s", warning.category.__name__, warning.message)

    async def _handle_request(
        self,
        message: RequestResponder[types.ClientRequest, types.ServerResult],
        req: Any,
        session: ServerSession,
        lifespan_context: LifespanResultT,
        raise_exceptions: bool,
        server_scope: TaskGroup | None = None,
    ):
        logger.info("Processing request of type %s", type(req).__name__)
        if handler := self.request_handlers.get(type(req)):  # type: ignore
            logger.debug("Dispatching request of type %s", type(req).__name__)

            context_token = None
            try:
                # Extract request context from message metadata
                request_data = None
                if message.message_metadata is not None and isinstance(message.message_metadata, ServerMessageMetadata):
                    request_data = message.message_metadata.request_context

                # Set our global state that can be retrieved via
                # app.get_request_context()
                context_token = request_ctx.set(
                    RequestContext(
                        request_id=message.request_id,
                        operation_token=message.operation.token if message.operation else None,
                        meta=message.request_meta,
                        session=session,
                        supports_async=self._client_supports_async(session),
                        lifespan_context=lifespan_context,
                        request=request_data,
                    )
                )
                response = await handler(req, server_scope)

                # Track async operations for cancellation
                if isinstance(req, types.CallToolRequest):
                    result = response.root
                    if isinstance(result, types.CallToolResult) and result.operation is not None:
                        # This is an async operation, track the request ID to token mapping
                        operation_token = result.operation.token
                        self._request_to_operation[message.request_id] = operation_token
                        logger.debug(f"Tracking async operation {operation_token} for request {message.request_id}")

            except McpError as err:
                response = err.error
            except anyio.get_cancelled_exc_class():
                logger.info(
                    "Request %s cancelled - duplicate response suppressed",
                    message.request_id,
                )
                return
            except Exception as err:
                if raise_exceptions:
                    raise err
                response = types.ErrorData(code=0, message=str(err), data=None)
            finally:
                # Reset the global state after we are done
                if context_token is not None:
                    request_ctx.reset(context_token)

            await message.respond(response)
        else:
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
            except Exception:
                logger.exception("Uncaught exception in notification handler")


async def _ping_handler(request: types.PingRequest, _: Any = None) -> types.ServerResult:
    return types.ServerResult(types.EmptyResult())
