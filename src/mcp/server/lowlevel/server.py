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
from typing import Any, Generic, TypeAlias, cast

import anyio
import jsonschema
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl
from typing_extensions import TypeVar

import mcp.types as types
from mcp.server.discovery import ToolGroup, ToolGroupManager
from mcp.server.lowlevel.func_inspection import create_call_wrapper
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder

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
        lifespan: Callable[
            [Server[LifespanResultT, RequestT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
    ):
        self.name = name
        self.version = version
        self.instructions = instructions
        self.website_url = website_url
        self.icons = icons
        self.lifespan = lifespan
        self.request_handlers: dict[type, Callable[..., Awaitable[types.ServerResult]]] = {
            types.PingRequest: _ping_handler,
        }
        self.notification_handlers: dict[type, Callable[..., Awaitable[None]]] = {}
        self._tool_cache: dict[str, types.Tool] = {}
        self._discovery: ToolGroupManager | None = None
        self._loaded_tool_groups: set[str] = set()
        logger.debug("Initializing server %r", name)

    @property
    def is_discovery_enabled(self) -> bool:
        """Check if progressive tool discovery is enabled.

        Returns True if discovery has been registered via register_discovery_tools(),
        False otherwise.
        """
        return self._discovery is not None

    def register_discovery_tools(self, manager: ToolGroupManager) -> None:
        """Enable progressive disclosure of tools through semantic grouping.

        When enabled, listTools() returns only gateway tools (one per tool group),
        and the LLM can call gateway tools to load the actual tools for that group.

        Args:
            manager: A ToolGroupManager instance that manages tool groups
        """
        self._discovery = manager
        logger.debug("Discovery tools registered for server %r", self.name)

    def enable_discovery_with_groups(
        self,
        items: list[ToolGroup | types.Tool | types.Resource | types.Prompt],
    ) -> None:
        """Enable progressive disclosure with programmatic tool groups.

        This is the unified way to set up progressive disclosure. You can pass
        a mix of ToolGroups, direct Tools, Resources, and Prompts in one call.
        The method automatically categorizes and registers each type appropriately.

        This is the recommended approach - simpler and more maintainable than
        using separate register_direct_tool/resource/prompt methods.

        Example:
            server = Server("my-server")

            # Single unified call for all primitives
            server.enable_discovery_with_groups([
                # Direct tool (always visible)
                divide_tool,

                # Direct resource (always visible)
                math_formulas_resource,

                # Tool groups (discovered progressively)
                ToolGroup(
                    name="math",
                    description="Math operations",
                    tools=[add_tool, subtract_tool],
                    prompts=[math_helper_prompt],
                ),
                ToolGroup(
                    name="weather",
                    description="Weather operations",
                    tools=[forecast_tool, geocode_tool],
                ),
            ])

        Args:
            items: List of mixed types:
                - ToolGroup: Tool groups for progressive discovery
                - types.Tool: Direct tools (always visible)
                - types.Resource: Direct resources (always visible)
                - types.Prompt: Direct prompts (always visible)
        """
        # Auto-categorize items by type
        groups: list[ToolGroup] = []
        direct_tools: list[types.Tool] = []
        direct_resources: list[types.Resource] = []
        direct_prompts: list[types.Prompt] = []

        for item in items:
            if isinstance(item, ToolGroup):
                groups.append(item)
            elif isinstance(item, types.Tool):
                direct_tools.append(item)
            elif isinstance(item, types.Resource):
                direct_resources.append(item)
            else:  # Must be types.Prompt (only remaining type)
                direct_prompts.append(item)

        # Register direct items (these are always visible)
        for tool in direct_tools:
            if not hasattr(self, "_direct_tools"):
                self._direct_tools = []  # type: ignore
            self._direct_tools.append(tool)  # type: ignore
            logger.debug("Registered direct tool: %s", tool.name)

        for resource in direct_resources:
            if not hasattr(self, "_direct_resources"):
                self._direct_resources = []  # type: ignore
            self._direct_resources.append(resource)  # type: ignore
            logger.debug("Registered direct resource: %s", resource.name)

        for prompt in direct_prompts:
            if not hasattr(self, "_direct_prompts"):
                self._direct_prompts = []  # type: ignore
            self._direct_prompts.append(prompt)  # type: ignore
            logger.debug("Registered direct prompt: %s", prompt.name)

        # Enable discovery for grouped items
        if groups:
            manager = ToolGroupManager(groups)
            self.register_discovery_tools(manager)
            logger.info(
                "Discovery enabled with %d tool groups: %s",
                len(groups),
                ", ".join(g.name for g in groups),
            )

        # Log summary of what was registered
        if direct_tools or direct_resources or direct_prompts:
            logger.info(
                "Registered %d direct tool(s), %d resource(s), %d prompt(s)",
                len(direct_tools),
                len(direct_resources),
                len(direct_prompts),
            )

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
            except Exception:  # pragma: no cover
                pass

            return "unknown"  # pragma: no cover

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
        if types.SetLevelRequest in self.request_handlers:  # pragma: no cover
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

            async def handler(req: types.ListPromptsRequest):
                result = await wrapper(req)
                # Handle both old style (list[Prompt]) and new style (ListPromptsResult)
                if isinstance(result, types.ListPromptsResult):
                    prompts = list(result.prompts) if result.prompts else []
                else:
                    # Old style returns list[Prompt]
                    prompts = list(result) if result else []

                # Add direct prompts (hybrid mode support)
                if hasattr(self, "_direct_prompts"):
                    direct_prompts: list[types.Prompt] = self._direct_prompts  # type: ignore
                    prompts.extend(direct_prompts)
                else:
                    direct_prompts = []

                # If discovery is enabled, add prompts from loaded groups
                if self.is_discovery_enabled and self._discovery is not None:
                    discovery_prompts_dicts = self._discovery.get_prompts_from_loaded_groups(self._loaded_tool_groups)
                    # Convert dicts to Prompt objects
                    discovery_prompts = [self._dict_to_prompt(p) for p in discovery_prompts_dicts]
                    prompts.extend(discovery_prompts)
                    logger.debug(
                        "Discovery enabled (hybrid mode): returning %d prompts "
                        "(%d from user handler + %d direct + %d from loaded groups)",
                        len(prompts),
                        len(result) if isinstance(result, list) else len(result.prompts) if result.prompts else 0,
                        len(direct_prompts),
                        len(discovery_prompts),
                    )

                return types.ServerResult(types.ListPromptsResult(prompts=prompts))

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

                # If discovery is enabled and user handler didn't find it (empty result),
                # search loaded groups
                if (
                    self.is_discovery_enabled
                    and self._discovery is not None
                    and (not prompt_get.messages or len(prompt_get.messages) == 0)
                ):
                    prompt_dict = self._discovery.find_prompt_in_groups(req.params.name, self._loaded_tool_groups)
                    if prompt_dict:
                        logger.debug("Found prompt %s in loaded groups", req.params.name)
                        prompt_obj = self._dict_to_prompt(prompt_dict)
                        # Return with description, empty messages (client will use Prompt object)
                        prompt_get = types.GetPromptResult(
                            description=prompt_obj.description,
                            messages=[],
                        )

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

            async def handler(req: types.ListResourcesRequest):
                result = await wrapper(req)
                # Handle both old style (list[Resource]) and new style (ListResourcesResult)
                if isinstance(result, types.ListResourcesResult):
                    resources = list(result.resources) if result.resources else []
                else:
                    # Old style returns list[Resource]
                    resources = list(result) if result else []

                # Add direct resources (hybrid mode support)
                if hasattr(self, "_direct_resources"):
                    direct_resources: list[types.Resource] = self._direct_resources  # type: ignore
                    resources.extend(direct_resources)
                else:
                    direct_resources = []

                # If discovery is enabled, add resources from loaded groups
                if self.is_discovery_enabled and self._discovery is not None:
                    discovery_resources_dicts = self._discovery.get_resources_from_loaded_groups(
                        self._loaded_tool_groups
                    )
                    # Convert dicts to Resource objects
                    discovery_resources = [self._dict_to_resource(r) for r in discovery_resources_dicts]
                    resources.extend(discovery_resources)
                    logger.debug(
                        "Discovery enabled (hybrid mode): returning %d resources "
                        "(%d from user handler + %d direct + %d from loaded groups)",
                        len(resources),
                        len(result) if isinstance(result, list) else len(result.resources) if result.resources else 0,
                        len(direct_resources),
                        len(discovery_resources),
                    )

                return types.ServerResult(types.ListResourcesResult(resources=resources))

            self.request_handlers[types.ListResourcesRequest] = handler
            return func

        return decorator

    def list_resource_templates(self):
        def decorator(func: Callable[[], Awaitable[list[types.ResourceTemplate]]]):
            logger.debug("Registering handler for ListResourceTemplatesRequest")

            async def handler(_: Any):
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

            async def handler(req: types.ReadResourceRequest):
                result: str | bytes | Iterable[ReadResourceContents] | None = None
                try:
                    result = await func(req.params.uri)
                except Exception:  # pragma: no cover
                    # User handler couldn't find the resource, try discovery
                    if self.is_discovery_enabled and self._discovery is not None:
                        resource_dict = self._discovery.find_resource_in_groups(
                            req.params.uri, self._loaded_tool_groups
                        )
                        if resource_dict:
                            logger.debug("Found resource %s in loaded groups", req.params.uri)
                            # Return the resource content (empty for now, client will use Resource definition)
                            return types.ServerResult(
                                types.ReadResourceResult(
                                    contents=[
                                        types.TextResourceContents(
                                            uri=req.params.uri,
                                            text="",
                                            mimeType=resource_dict.get("mimeType", "text/plain"),
                                        )
                                    ],
                                )
                            )
                    # If not found in discovery either, re-raise the original exception
                    raise

                def create_content(data: str | bytes, mime_type: str | None):
                    match data:
                        case str() as data:
                            return types.TextResourceContents(
                                uri=req.params.uri,
                                text=data,
                                mimeType=mime_type or "text/plain",
                            )
                        case bytes() as data:  # pragma: no cover
                            import base64

                            return types.BlobResourceContents(
                                uri=req.params.uri,
                                blob=base64.b64encode(data).decode(),
                                mimeType=mime_type or "application/octet-stream",
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
                            create_content(content_item.content, content_item.mime_type) for content_item in contents
                        ]
                        return types.ServerResult(
                            types.ReadResourceResult(
                                contents=contents_list,
                            )
                        )

                return types.ServerResult(  # pragma: no cover
                    types.ReadResourceResult(
                        contents=[content],
                    )
                )

            self.request_handlers[types.ReadResourceRequest] = handler
            return func

        return decorator

    def set_logging_level(self):  # pragma: no cover
        def decorator(func: Callable[[types.LoggingLevel], Awaitable[None]]):
            logger.debug("Registering handler for SetLevelRequest")

            async def handler(req: types.SetLevelRequest):
                await func(req.params.level)
                return types.ServerResult(types.EmptyResult())

            self.request_handlers[types.SetLevelRequest] = handler
            return func

        return decorator

    def subscribe_resource(self):  # pragma: no cover
        def decorator(func: Callable[[AnyUrl], Awaitable[None]]):
            logger.debug("Registering handler for SubscribeRequest")

            async def handler(req: types.SubscribeRequest):
                await func(req.params.uri)
                return types.ServerResult(types.EmptyResult())

            self.request_handlers[types.SubscribeRequest] = handler
            return func

        return decorator

    def unsubscribe_resource(self):  # pragma: no cover
        def decorator(func: Callable[[AnyUrl], Awaitable[None]]):
            logger.debug("Registering handler for UnsubscribeRequest")

            async def handler(req: types.UnsubscribeRequest):
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

            async def handler(req: types.ListToolsRequest):
                # If discovery is enabled, return gateway tools + any loaded group tools
                if self.is_discovery_enabled and self._discovery is not None:
                    result_tools: list[types.Tool] = []

                    # Include only gateway tools for groups NOT yet loaded
                    # Once a group is loaded, hide its gateway to reduce context bloat
                    gateway_tool_objects: list[types.Tool] = []
                    for group_name in self._discovery.get_group_names():
                        # Only include gateway if its group hasn't been loaded yet
                        if group_name not in self._loaded_tool_groups:
                            description = self._discovery.get_group_description(group_name)
                            gateway_tool: dict[str, Any] = {  # type: ignore
                                "name": group_name,  # Gateway tool named directly after group
                                "description": description,
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {},
                                    "required": [],
                                    "x-gateway": True,  # Explicit marker for gateway tools
                                },
                            }
                            gateway_tool_objects.append(self._dict_to_tool(gateway_tool))  # type: ignore
                    result_tools.extend(gateway_tool_objects)  # type: ignore

                    # Add tools from any already-loaded groups
                    for group_name in self._loaded_tool_groups:
                        group_tools = self._discovery.get_group_tools(group_name)
                        # Filter out nested gateways for groups that are ALSO already loaded
                        # But keep sibling gateways available
                        filtered_tools: list[dict[str, Any]] = []  # type: ignore
                        for tool in group_tools:
                            tool_name = tool.get("name", "")  # type: ignore
                            # Check if this is a gateway tool for another group
                            if self._discovery.is_gateway_tool(tool_name):
                                nested_group_name = self._discovery.extract_group_name(tool_name)
                                if (
                                    nested_group_name
                                    and nested_group_name in self._loaded_tool_groups
                                    and nested_group_name != group_name
                                ):
                                    # Skip this gateway tool only if it's for a DIFFERENT
                                    # already-loaded group. Keep sibling gateways available.
                                    logger.debug(
                                        "Filtering out nested gateway %s (group %s already loaded)",
                                        tool_name,
                                        nested_group_name,
                                    )
                                    continue
                            filtered_tools.append(tool)  # type: ignore
                        group_tool_objects: list[types.Tool] = [
                            self._dict_to_tool(tool)
                            for tool in filtered_tools  # type: ignore
                        ]
                        result_tools.extend(group_tool_objects)  # type: ignore

                    # Add direct tools (hybrid mode support)
                    # These are tools registered directly via register_tool()
                    if hasattr(self, "_direct_tools"):
                        direct_tools: list[types.Tool] = self._direct_tools  # type: ignore
                        result_tools.extend(direct_tools)
                    else:
                        direct_tools = []

                    # Update cache with all returned tools
                    for tool in result_tools:
                        self._tool_cache[tool.name] = tool

                    logger.debug(
                        "Discovery enabled (hybrid mode): returning %d tools "
                        "(%d unloaded gateways + %d from %d loaded groups + %d direct tools)",
                        len(result_tools),  # type: ignore
                        len(gateway_tool_objects),
                        sum(len(self._discovery.get_group_tools(g)) for g in self._loaded_tool_groups),  # type: ignore
                        len(self._loaded_tool_groups),
                        len(direct_tools),
                    )
                    return types.ServerResult(types.ListToolsResult(tools=result_tools))

                result = await wrapper(req)

                # Handle both old style (list[Tool]) and new style (ListToolsResult)
                if isinstance(result, types.ListToolsResult):  # pragma: no cover
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

    def _dict_to_tool(self, tool_dict: dict[str, Any]) -> types.Tool:
        """Convert a tool dictionary to a types.Tool object.

        Args:
            tool_dict: Dictionary with tool definition (name, description, inputSchema, outputSchema)

        Returns:
            A types.Tool object
        """
        return types.Tool(
            name=tool_dict.get("name", ""),
            description=tool_dict.get("description", ""),
            inputSchema=tool_dict.get("inputSchema", {"type": "object"}),
            outputSchema=tool_dict.get("outputSchema"),
        )

    def _dict_to_prompt(self, prompt_dict: dict[str, Any]) -> types.Prompt:
        """Convert a prompt dictionary to a types.Prompt object.

        Args:
            prompt_dict: Dictionary with prompt definition (name, description, arguments)

        Returns:
            A types.Prompt object
        """
        arguments: list[types.PromptArgument] = []
        if "arguments" in prompt_dict and prompt_dict["arguments"]:
            arguments.extend(
                types.PromptArgument(
                    name=arg.get("name", ""),
                    description=arg.get("description", ""),
                    required=arg.get("required", False),
                )
                for arg in prompt_dict["arguments"]
            )
        return types.Prompt(
            name=prompt_dict.get("name", ""),
            description=prompt_dict.get("description", ""),
            arguments=arguments,
        )

    def _dict_to_resource(self, resource_dict: dict[str, Any]) -> types.Resource:
        """Convert a resource dictionary to a types.Resource object.

        Args:
            resource_dict: Dictionary with resource definition (uri, name, description, mimeType)

        Returns:
            A types.Resource object
        """
        return types.Resource(
            uri=AnyUrl(resource_dict.get("uri", "file://unknown")),
            name=resource_dict.get("name", ""),
            description=resource_dict.get("description", ""),
            mimeType=resource_dict.get("mimeType", "text/plain"),
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
                Awaitable[UnstructuredContent | StructuredContent | CombinationContent | types.CallToolResult],
            ],
        ):
            logger.debug("Registering handler for CallToolRequest")

            async def handler(req: types.CallToolRequest):
                try:
                    tool_name = req.params.name
                    arguments = req.params.arguments or {}

                    # If discovery is enabled and this is a gateway tool, return its tools
                    if (
                        self.is_discovery_enabled
                        and self._discovery is not None
                        and self._discovery.is_gateway_tool(tool_name)
                    ):
                        group_name = self._discovery.extract_group_name(tool_name)
                        if group_name:
                            # Track that this group has been loaded
                            self._loaded_tool_groups.add(group_name)
                            tools = self._discovery.get_group_tools(group_name)
                            # Convert tools to types.Tool objects
                            tool_objects = [self._dict_to_tool(tool) for tool in tools]
                            # Update tool cache with these tools
                            for tool in tool_objects:
                                self._tool_cache[tool.name] = tool
                            logger.debug(
                                "Gateway tool %s called: returning %d tools for group %s",
                                tool_name,
                                len(tool_objects),
                                group_name,
                            )
                            # Notify client that tools have changed (for progressive disclosure)
                            try:
                                ctx = request_ctx.get()
                                await ctx.session.send_notification(
                                    types.ServerNotification(types.ToolListChangedNotification()),
                                    related_request_id=ctx.request_id,
                                )
                            except LookupError:  # pragma: no cover
                                # Request context not available; skip notification
                                logger.debug(
                                    "Could not send ToolListChangedNotification: request context not available"
                                )
                            # Return tools as text content
                            tool_descriptions = [f"- {t.name}: {t.description}" for t in tool_objects]
                            return types.ServerResult(
                                types.CallToolResult(
                                    content=[
                                        types.TextContent(
                                            type="text",
                                            text="Available tools:\n" + "\n".join(tool_descriptions),
                                        )
                                    ],
                                    isError=False,
                                )
                            )

                    tool = await self._get_cached_tool_definition(tool_name)

                    # input validation
                    if validate_input and tool:
                        try:
                            jsonschema.validate(instance=arguments, schema=tool.inputSchema)
                        except jsonschema.ValidationError as e:
                            return self._make_error_result(f"Input validation error: {e.message}")

                    # tool call
                    results = await func(tool_name, arguments)

                    # output normalization
                    unstructured_content: UnstructuredContent
                    maybe_structured_content: StructuredContent | None
                    if isinstance(results, types.CallToolResult):
                        return types.ServerResult(results)
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
                    if tool and tool.outputSchema is not None:
                        if maybe_structured_content is None:
                            return self._make_error_result(
                                "Output validation error: outputSchema defined but no structured output returned"
                            )
                        else:
                            try:
                                jsonschema.validate(instance=maybe_structured_content, schema=tool.outputSchema)
                            except jsonschema.ValidationError as e:
                                return self._make_error_result(f"Output validation error: {e.message}")

                    # result
                    return types.ServerResult(
                        types.CallToolResult(
                            content=list(unstructured_content),
                            structuredContent=maybe_structured_content,
                            isError=False,
                        )
                    )
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

            async def handler(req: types.CompleteRequest):
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
                case RequestResponder(request=types.ClientRequest(root=req)) as responder:
                    with responder:
                        await self._handle_request(message, req, session, lifespan_context, raise_exceptions)
                case types.ClientNotification(root=notify):
                    await self._handle_notification(notify)
                case Exception():  # pragma: no cover
                    logger.error(f"Received exception from stream: {message}")
                    await session.send_log_message(
                        level="error",
                        data="Internal Server Error",
                        logger="mcp.server.exception_handler",
                    )
                    if raise_exceptions:
                        raise message

            for warning in w:  # pragma: no cover
                logger.info("Warning: %s: %s", warning.category.__name__, warning.message)

    async def _handle_request(
        self,
        message: RequestResponder[types.ClientRequest, types.ServerResult],
        req: Any,
        session: ServerSession,
        lifespan_context: LifespanResultT,
        raise_exceptions: bool,
    ):
        logger.info("Processing request of type %s", type(req).__name__)
        if handler := self.request_handlers.get(type(req)):  # type: ignore
            logger.debug("Dispatching request of type %s", type(req).__name__)

            token = None
            try:
                # Extract request context from message metadata
                request_data = None
                if message.message_metadata is not None and isinstance(
                    message.message_metadata, ServerMessageMetadata
                ):  # pragma: no cover
                    request_data = message.message_metadata.request_context

                # Set our global state that can be retrieved via
                # app.get_request_context()
                token = request_ctx.set(
                    RequestContext(
                        message.request_id,
                        message.request_meta,
                        session,
                        lifespan_context,
                        request=request_data,
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


async def _ping_handler(_request: types.PingRequest) -> types.ServerResult:
    return types.ServerResult(types.EmptyResult())
