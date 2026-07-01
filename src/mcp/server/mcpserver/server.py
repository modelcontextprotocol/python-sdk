"""MCPServer - A more ergonomic interface for MCP servers."""

from __future__ import annotations

import base64
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Generic, Literal, TypeVar, overload

import anyio
import pydantic_core
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    Annotations,
    BlobResourceContents,
    CallToolRequestParams,
    CallToolResult,
    ClientCapabilities,
    CompleteRequestParams,
    CompleteResult,
    Completion,
    GetPromptRequestParams,
    GetPromptResult,
    Icon,
    InputRequiredResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    MissingRequiredClientCapabilityErrorData,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
    ToolAnnotations,
)
from mcp_types import Prompt as MCPPrompt
from mcp_types import PromptArgument as MCPPromptArgument
from mcp_types import Resource as MCPResource
from mcp_types import ResourceTemplate as MCPResourceTemplate
from mcp_types import Tool as MCPTool
from pydantic.networks import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, ProviderTokenVerifier, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheableMethod, CacheHint
from mcp.server.context import HandlerResult, ServerRequestContext
from mcp.server.extension import (
    Extension,
    MethodBinding,
    RequestHandler,
    compose_tool_call_interceptor,
    validate_extension_identifier,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import LifespanResultT, Server
from mcp.server.lowlevel.server import lifespan as default_lifespan
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
from mcp.server.mcpserver.prompts import Prompt, PromptManager
from mcp.server.mcpserver.resources import (
    DEFAULT_RESOURCE_SECURITY,
    FunctionResource,
    Resource,
    ResourceManager,
    ResourceSecurity,
)
from mcp.server.mcpserver.tools import Tool, ToolManager
from mcp.server.mcpserver.utilities.context_injection import find_context_parameter
from mcp.server.mcpserver.utilities.logging import configure_logging, get_logger
from mcp.server.request_state import RequestStateBoundary, RequestStateSecurity
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, SubscriptionBus
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.shared.uri_template import UriTemplate

logger = get_logger(__name__)

_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])


class Settings(BaseSettings, Generic[LifespanResultT]):
    """MCPServer settings.

    All settings can be configured via environment variables with the prefix MCP_.
    For example, MCP_DEBUG=true will set debug=True.
    """

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        extra="ignore",
    )

    # Server settings
    debug: bool
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    # resource settings
    warn_on_duplicate_resources: bool

    # tool settings
    warn_on_duplicate_tools: bool

    # prompt settings
    warn_on_duplicate_prompts: bool

    dependencies: list[str]
    """List of dependencies to install in the server environment. Used by the `mcp install` and `mcp dev` CLI."""

    lifespan: Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None
    """An async context manager that will be called when the server is started."""

    auth: AuthSettings | None


_MISSING_AUDIENCE = (
    "request_state_security is configured but this server has no name. Sealed\n"
    "requestState carries the server name as an audience claim, so state minted by\n"
    "another service that shares the same keys is rejected; unnamed servers would\n"
    "all stamp the same placeholder and the check would mean nothing. Name the\n"
    'server (MCPServer("my-service", ...)) or set RequestStateSecurity(audience=...).'
)


def lifespan_wrapper(
    app: MCPServer[LifespanResultT],
    lifespan: Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]],
) -> Callable[[Server[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]]:
    @asynccontextmanager
    async def wrap(_: Server[LifespanResultT]) -> AsyncIterator[LifespanResultT]:
        async with lifespan(app) as context:
            yield context

    return wrap


class MCPServer(Generic[LifespanResultT]):
    def __init__(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[Icon] | None = None,
        version: str | None = None,
        auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
        token_verifier: TokenVerifier | None = None,
        *,
        tools: list[Tool] | None = None,
        resources: list[Resource] | None = None,
        extensions: Sequence[Extension] | None = None,
        debug: bool = False,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
        warn_on_duplicate_resources: bool = True,
        warn_on_duplicate_tools: bool = True,
        warn_on_duplicate_prompts: bool = True,
        dependencies: list[str] | None = None,
        lifespan: Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None = None,
        auth: AuthSettings | None = None,
        resource_security: ResourceSecurity = DEFAULT_RESOURCE_SECURITY,
        request_state_security: RequestStateSecurity | None = None,
        cache_hints: Mapping[CacheableMethod, CacheHint] | None = None,
        subscriptions: SubscriptionBus | None = None,
    ):
        self._resource_security = resource_security
        self.settings = Settings(
            debug=debug,
            log_level=log_level,
            warn_on_duplicate_resources=warn_on_duplicate_resources,
            warn_on_duplicate_tools=warn_on_duplicate_tools,
            warn_on_duplicate_prompts=warn_on_duplicate_prompts,
            dependencies=dependencies or [],
            lifespan=lifespan,
            auth=auth,
        )
        self.dependencies = self.settings.dependencies

        self._tool_manager = ToolManager(tools=tools, warn_on_duplicate_tools=self.settings.warn_on_duplicate_tools)
        self._resource_manager = ResourceManager(
            resources=resources, warn_on_duplicate_resources=self.settings.warn_on_duplicate_resources
        )
        self._prompt_manager = PromptManager(warn_on_duplicate_prompts=self.settings.warn_on_duplicate_prompts)
        # The subscriptions/listen fan-out seam (2026-07-28). The default bus is
        # in-process; pass an `SubscriptionBus` implementation over an external pub/sub
        # backend to fan events out across replicas.
        self._subscriptions: SubscriptionBus = subscriptions if subscriptions is not None else InMemorySubscriptionBus()
        self._lowlevel_server = Server(
            name=name or "mcp-server",
            title=title,
            description=description,
            instructions=instructions,
            website_url=website_url,
            icons=icons,
            version=version,
            cache_hints=cache_hints,
            on_list_tools=self._handle_list_tools,
            on_call_tool=self._handle_call_tool,
            on_list_resources=self._handle_list_resources,
            on_read_resource=self._handle_read_resource,
            on_list_resource_templates=self._handle_list_resource_templates,
            on_list_prompts=self._handle_list_prompts,
            on_get_prompt=self._handle_get_prompt,
            on_subscriptions_listen=ListenHandler(self._subscriptions),
            # TODO(Marcelo): It seems there's a type mismatch between the lifespan type from an MCPServer and Server.
            # We need to create a Lifespan type that is a generic on the server type, like Starlette does.
            lifespan=(lifespan_wrapper(self, self.settings.lifespan) if self.settings.lifespan else default_lifespan),  # type: ignore
        )
        # Ordering: inside OpenTelemetry (spans record the sealed wire form),
        # outside extension interceptors (extensions see plaintext).
        if request_state_security is None:
            security = RequestStateSecurity.ephemeral()
        else:
            # A supplied policy usually means shared keys, where the audience claim is
            # what separates services; an unnamed server would stamp the placeholder.
            if not name and request_state_security.audience is None:
                raise ValueError(_MISSING_AUDIENCE)
            security = request_state_security
        self._lowlevel_server.middleware.append(RequestStateBoundary(security, default_audience=self.name))
        # Validate auth configuration
        if self.settings.auth is not None:
            if auth_server_provider and token_verifier:  # pragma: no cover
                raise ValueError("Cannot specify both auth_server_provider and token_verifier")
            if not auth_server_provider and not token_verifier:  # pragma: no cover
                raise ValueError("Must specify either auth_server_provider or token_verifier when auth is enabled")
        elif auth_server_provider or token_verifier:
            raise ValueError("Cannot specify auth_server_provider or token_verifier without auth settings")

        self._auth_server_provider = auth_server_provider
        self._token_verifier = token_verifier

        # Create token verifier from provider if needed (backwards compatibility)
        if auth_server_provider and not token_verifier:
            self._token_verifier = ProviderTokenVerifier(auth_server_provider)
        self._custom_starlette_routes: list[Route] = []

        # Configure logging
        configure_logging(self.settings.log_level)

        self._extensions: list[Extension] = []
        for extension in extensions or ():
            self._apply_extension(extension)
        self._install_extension_interceptor()

    @property
    def name(self) -> str:
        return self._lowlevel_server.name

    @property
    def title(self) -> str | None:
        return self._lowlevel_server.title

    @property
    def description(self) -> str | None:
        return self._lowlevel_server.description

    @property
    def instructions(self) -> str | None:
        return self._lowlevel_server.instructions

    @property
    def website_url(self) -> str | None:
        return self._lowlevel_server.website_url

    @property
    def icons(self) -> list[Icon] | None:
        return self._lowlevel_server.icons

    @property
    def version(self) -> str | None:
        return self._lowlevel_server.version

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """Get the StreamableHTTP session manager.

        This is exposed to enable advanced use cases like mounting multiple
        MCPServer instances in a single FastAPI application.

        Raises:
            RuntimeError: If called before streamable_http_app() has been called.
        """
        return self._lowlevel_server.session_manager

    def _apply_extension(self, extension: Extension) -> None:
        """Apply one opt-in extension's contributions through the public surface.

        Registers its tools/resources/methods and advertises its settings under
        `ServerCapabilities.extensions[extension.identifier]`. Extensions are fixed
        at construction, so this is private; the `tools/call` interceptor is
        composed once afterwards by `_install_extension_interceptor`.
        """
        identifier = getattr(extension, "identifier", None)
        validate_extension_identifier(identifier, owner=type(extension).__name__)
        if any(e.identifier == identifier for e in self._extensions):
            raise ValueError(f"Extension {identifier!r} is already registered")
        self._extensions.append(extension)

        for tool in extension.tools():
            self.add_tool(tool.fn, meta=tool.meta, **tool.kwargs)
        for resource in extension.resources():
            self.add_resource(resource.resource)
        for method in extension.methods():
            if self._lowlevel_server.get_request_handler(method.method) is not None:
                raise ValueError(
                    f"Extension {identifier!r} binds method {method.method!r}, which is already "
                    "registered; extension methods are additive and cannot replace another handler"
                )
            handler = _version_gated(method) if method.protocol_versions is not None else method.handler
            self._lowlevel_server.add_request_handler(method.method, method.params_type, handler)

        self._lowlevel_server.extensions[extension.identifier] = extension.settings()

    def _install_extension_interceptor(self) -> None:
        """Compose every extension's `tools/call` interceptor into one middleware.

        Installed only when at least one extension overrides `intercept_tool_call`,
        so a server with purely additive extensions adds no middleware.
        """
        if any(type(e).intercept_tool_call is not Extension.intercept_tool_call for e in self._extensions):
            self._lowlevel_server.middleware.append(compose_tool_call_interceptor(self._extensions))

    @overload
    def run(
        self,
        transport: Literal["stdio"] = ...,
        *,
        stdin: anyio.AsyncFile[str] | None = ...,
        stdout: anyio.AsyncFile[str] | None = ...,
    ) -> None: ...

    @overload
    def run(
        self,
        transport: Literal["sse"],
        *,
        host: str = ...,
        port: int = ...,
        sse_path: str = ...,
        message_path: str = ...,
        transport_security: TransportSecuritySettings | None = ...,
    ) -> None: ...

    @overload
    def run(
        self,
        transport: Literal["streamable-http"],
        *,
        host: str = ...,
        port: int = ...,
        streamable_http_path: str = ...,
        json_response: bool = ...,
        stateless_http: bool = ...,
        event_store: EventStore | None = ...,
        retry_interval: int | None = ...,
        transport_security: TransportSecuritySettings | None = ...,
    ) -> None: ...

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        **kwargs: Any,
    ) -> None:
        """Run the MCP server. Note this is a synchronous function.

        Args:
            transport: Transport protocol to use ("stdio", "sse", or "streamable-http")
            **kwargs: Transport-specific options (see overloads for details)
        """
        TRANSPORTS = Literal["stdio", "sse", "streamable-http"]
        if transport not in TRANSPORTS.__args__:  # type: ignore  # pragma: no cover
            raise ValueError(f"Unknown transport: {transport}")

        match transport:
            case "stdio":
                anyio.run(lambda: self.run_stdio_async(**kwargs))
            case "sse":  # pragma: no cover
                anyio.run(lambda: self.run_sse_async(**kwargs))
            case "streamable-http":  # pragma: no cover
                anyio.run(lambda: self.run_streamable_http_async(**kwargs))

    async def _handle_list_tools(
        self, ctx: ServerRequestContext[LifespanResultT], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=await self.list_tools())

    async def _handle_call_tool(
        self, ctx: ServerRequestContext[LifespanResultT], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        context = Context(request_context=ctx, mcp_server=self, input_params=params, subscriptions=self._subscriptions)
        try:
            return await self.call_tool(params.name, params.arguments or {}, context)
        except MCPError:
            raise
        except Exception as e:
            return CallToolResult(content=[TextContent(type="text", text=str(e))], is_error=True)

    async def _handle_list_resources(
        self, ctx: ServerRequestContext[LifespanResultT], params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=await self.list_resources())

    async def _handle_read_resource(
        self, ctx: ServerRequestContext[LifespanResultT], params: ReadResourceRequestParams
    ) -> ReadResourceResult | InputRequiredResult:
        context = Context(request_context=ctx, mcp_server=self, input_params=params, subscriptions=self._subscriptions)
        try:
            results = await self.read_resource(params.uri, context)
        except ResourceNotFoundError as err:
            raise MCPError(code=INVALID_PARAMS, message=str(err), data={"uri": str(params.uri)})
        except ResourceError as err:
            raise MCPError(code=INTERNAL_ERROR, message=str(err), data={"uri": str(params.uri)})
        if isinstance(results, InputRequiredResult):
            return results
        contents: list[TextResourceContents | BlobResourceContents] = []
        for item in results:
            if isinstance(item.content, bytes):
                contents.append(
                    BlobResourceContents(
                        uri=params.uri,
                        blob=base64.b64encode(item.content).decode(),
                        mime_type=item.mime_type or "application/octet-stream",
                        _meta=item.meta,
                    )
                )
            else:
                contents.append(
                    TextResourceContents(
                        uri=params.uri,
                        text=item.content,
                        mime_type=item.mime_type or "text/plain",
                        _meta=item.meta,
                    )
                )
        return ReadResourceResult(contents=contents)

    async def _handle_list_resource_templates(
        self, ctx: ServerRequestContext[LifespanResultT], params: PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        return ListResourceTemplatesResult(resource_templates=await self.list_resource_templates())

    async def _handle_list_prompts(
        self, ctx: ServerRequestContext[LifespanResultT], params: PaginatedRequestParams | None
    ) -> ListPromptsResult:
        return ListPromptsResult(prompts=await self.list_prompts())

    async def _handle_get_prompt(
        self, ctx: ServerRequestContext[LifespanResultT], params: GetPromptRequestParams
    ) -> GetPromptResult | InputRequiredResult:
        context = Context(request_context=ctx, mcp_server=self, input_params=params, subscriptions=self._subscriptions)
        return await self.get_prompt(params.name, params.arguments, context)

    async def list_tools(self) -> list[MCPTool]:
        """List all available tools."""
        tools = self._tool_manager.list_tools()
        return [
            MCPTool(
                name=info.name,
                title=info.title,
                description=info.description,
                input_schema=info.parameters,
                output_schema=info.output_schema,
                annotations=info.annotations,
                icons=info.icons,
                _meta=info.meta,
            )
            for info in tools
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[LifespanResultT, Any] | None = None
    ) -> CallToolResult | InputRequiredResult:
        """Call a tool by name with arguments."""
        if context is None:
            context = Context(mcp_server=self, subscriptions=self._subscriptions)
        return await self._tool_manager.call_tool(name, arguments, context, convert_result=True)

    async def list_resources(self) -> list[MCPResource]:
        """List all available resources."""

        resources = self._resource_manager.list_resources()
        return [
            MCPResource(
                uri=resource.uri,
                name=resource.name or "",
                title=resource.title,
                description=resource.description,
                mime_type=resource.mime_type,
                icons=resource.icons,
                annotations=resource.annotations,
                _meta=resource.meta,
            )
            for resource in resources
        ]

    async def list_resource_templates(self) -> list[MCPResourceTemplate]:
        templates = self._resource_manager.list_templates()
        return [
            MCPResourceTemplate(
                uri_template=template.uri_template,
                name=template.name,
                title=template.title,
                description=template.description,
                mime_type=template.mime_type,
                icons=template.icons,
                annotations=template.annotations,
                _meta=template.meta,
            )
            for template in templates
        ]

    async def read_resource(
        self, uri: AnyUrl | str, context: Context[LifespanResultT, Any] | None = None
    ) -> Iterable[ReadResourceContents] | InputRequiredResult:
        """Read a resource by URI.

        An `InputRequiredResult` returned by a resource template function is
        passed through unchanged (the 2026-07-28 multi-round-trip flow); the
        retry's answers arrive on `ctx.input_responses`, with
        `ctx.request_state` carrying the echoed opaque state.

        Raises:
            ResourceNotFoundError: If no resource or template matches the URI.
            ResourceError: If template creation or resource reading fails.
        """
        if context is None:
            context = Context(mcp_server=self, subscriptions=self._subscriptions)
        resource = await self._resource_manager.get_resource(uri, context)
        if isinstance(resource, InputRequiredResult):
            return resource

        try:
            content = await resource.read()
            return [ReadResourceContents(content=content, mime_type=resource.mime_type, meta=resource.meta)]
        except MCPError:
            raise
        except Exception as exc:
            logger.exception(f"Error getting resource {uri}")
            # If an exception happens when reading the resource, we should not leak the exception to the client.
            raise ResourceError(f"Error reading resource {uri}") from exc

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        """Add a tool to the server.

        The tool function can optionally request a Context object by adding a parameter
        with the Context type annotation. See the @tool decorator for examples.

        Args:
            fn: The function to register as a tool
            name: Optional name for the tool (defaults to function name)
            title: Optional human-readable title for the tool
            description: Optional description of what the tool does
            annotations: Optional ToolAnnotations providing additional tool information
            icons: Optional list of icons for the tool
            meta: Optional metadata dictionary for the tool
            structured_output: Controls whether the tool's output is structured or unstructured
                - If None, auto-detects based on the function's return type annotation
                - If True, creates a structured tool (return type annotation permitting)
                - If False, unconditionally creates an unstructured tool
        """
        self._tool_manager.add_tool(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )

    def remove_tool(self, name: str) -> None:
        """Remove a tool from the server by name.

        Args:
            name: The name of the tool to remove

        Raises:
            ToolError: If the tool does not exist
        """
        self._tool_manager.remove_tool(name)

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[_CallableT], _CallableT]:
        """Decorator to register a tool.

        Tools can optionally request a Context object by adding a parameter with the
        Context type annotation. The context provides access to MCP capabilities like
        logging, progress reporting, and resource access.

        Args:
            name: Optional name for the tool (defaults to function name)
            title: Optional human-readable title for the tool
            description: Optional description of what the tool does
            annotations: Optional ToolAnnotations providing additional tool information
            icons: Optional list of icons for the tool
            meta: Optional metadata dictionary for the tool
            structured_output: Controls whether the tool's output is structured or unstructured
                - If None, auto-detects based on the function's return type annotation
                - If True, creates a structured tool (return type annotation permitting)
                - If False, unconditionally creates an unstructured tool

        Example:
            ```python
            @server.tool()
            def my_tool(x: int) -> str:
                return str(x)
            ```

            ```python
            @server.tool()
            async def tool_with_context(x: int, ctx: Context) -> str:
                await ctx.info(f"Processing {x}")
                return str(x)
            ```

            ```python
            @server.tool()
            async def async_tool(x: int, context: Context) -> str:
                await context.report_progress(50, 100)
                return str(x)
            ```
        """
        # Check if user passed function directly instead of calling decorator
        if callable(name):
            raise TypeError(
                "The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool"
            )

        def decorator(fn: _CallableT) -> _CallableT:
            self.add_tool(
                fn,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )
            return fn

        return decorator

    def completion(self):
        """Decorator to register a completion handler.

        The completion handler receives:
        - ref: PromptReference or ResourceTemplateReference
        - argument: CompletionArgument with name and partial value
        - context: Optional CompletionContext with previously resolved arguments

        Example:
            ```python
            @mcp.completion()
            async def handle_completion(ref, argument, context):
                if isinstance(ref, ResourceTemplateReference):
                    # Return completions based on ref, argument, and context
                    return Completion(values=["option1", "option2"])
                return None
            ```
        """

        def decorator(func: _CallableT) -> _CallableT:
            async def handler(
                ctx: ServerRequestContext[LifespanResultT], params: CompleteRequestParams
            ) -> CompleteResult:
                result = await func(params.ref, params.argument, params.context)
                return CompleteResult(
                    completion=result if result is not None else Completion(values=[], total=None, has_more=None),
                )

            self._lowlevel_server.add_request_handler("completion/complete", CompleteRequestParams, handler)
            return func

        return decorator

    def add_resource(self, resource: Resource) -> None:
        """Add a resource to the server.

        Args:
            resource: A Resource instance to add
        """
        self._resource_manager.add_resource(resource)

    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        icons: list[Icon] | None = None,
        annotations: Annotations | None = None,
        meta: dict[str, Any] | None = None,
        security: ResourceSecurity | None = None,
    ) -> Callable[[_CallableT], _CallableT]:
        """Decorator to register a function as a resource.

        The function will be called when the resource is read to generate its content.
        The function can return:
        - str for text content
        - bytes for binary content
        - an InputRequiredResult (template resources only; passed through
          unchanged for the 2026-07-28 multi-round-trip flow — read
          `ctx.input_responses` on the retry)
        - other types will be converted to JSON

        If the URI contains parameters (e.g. "resource://{param}"), it is
        registered as a template resource. Otherwise it is registered as a
        static resource; function parameters on a static URI raise an error.

        Args:
            uri: URI for the resource (e.g. "resource://my-resource" or "resource://{param}")
            name: Optional name for the resource
            title: Optional human-readable title for the resource
            description: Optional description of the resource
            mime_type: Optional MIME type for the resource
            icons: Optional list of icons for the resource
            annotations: Optional annotations for the resource
            meta: Optional metadata dictionary for the resource
            security: Path-safety policy for extracted template parameters.
                Defaults to the server's ``resource_security`` setting.
                Only applies to template resources.

        Example:
            ```python
            @server.resource("resource://my-resource")
            def get_data() -> str:
                return "Hello, world!"

            @server.resource("resource://my-resource")
            async def get_data() -> str:
                data = await fetch_data()
                return f"Hello, world! {data}"

            @server.resource("resource://{city}/weather")
            def get_weather(city: str) -> str:
                return f"Weather for {city}"

            @server.resource("resource://{city}/weather")
            async def get_weather(city: str) -> str:
                data = await fetch_weather(city)
                return f"Weather for {city}: {data}"
            ```

        Raises:
            InvalidUriTemplate: If ``uri`` is not a valid RFC 6570 template.
            ValueError: If URI template parameters don't match the
                function's parameters, or if a parameter bound to a
                ``{?...}``/``{&...}`` query variable has no default
                (the client may omit it).
            TypeError: If the decorator is applied without being called
                (``@resource`` instead of ``@resource("uri")``).
        """
        # Check if user passed function directly instead of calling decorator
        if callable(uri):
            raise TypeError(
                "The @resource decorator was used incorrectly. "
                "Did you forget to call it? Use @resource('uri') instead of @resource"
            )

        # Parse once, early — surfaces malformed-template errors at
        # decoration time with a clear position, and gives us correct
        # variable names for all RFC 6570 operators.
        parsed = UriTemplate.parse(uri)
        uri_params = set(parsed.variable_names)

        def decorator(fn: _CallableT) -> _CallableT:
            sig = inspect.signature(fn)
            context_param = find_context_parameter(fn)
            func_params = {p for p in sig.parameters.keys() if p != context_param}

            # Template/static is decided purely by the URI: variables
            # present means template, none means static.
            if uri_params:
                if uri_params != func_params:
                    raise ValueError(
                        f"Mismatch between URI parameters {uri_params} and function parameters {func_params}"
                    )

                # A {?...}/{&...} query variable is optional on the wire:
                # match() omits it from the extracted parameters when the
                # client leaves it out of the URI. The handler parameter
                # bound to it must therefore have a Python default; without
                # one, the author only finds out on the first request that
                # omits it, as an opaque internal error.
                missing_defaults = sorted(
                    name
                    for name in parsed.query_variable_names
                    if sig.parameters[name].default is inspect.Parameter.empty
                )
                if missing_defaults:
                    raise ValueError(
                        f"Resource {uri!r}: query parameter(s) {missing_defaults} have no "
                        f"default value. A client may omit a {{?...}}/{{&...}} query "
                        f"parameter, so the matching handler parameter must declare a "
                        f"default."
                    )

                # Register as template
                self._resource_manager.add_template(
                    fn=fn,
                    uri_template=uri,
                    name=name,
                    title=title,
                    description=description,
                    mime_type=mime_type,
                    icons=icons,
                    annotations=annotations,
                    security=security if security is not None else self._resource_security,
                    meta=meta,
                )
            else:
                if func_params:
                    raise ValueError(
                        f"Resource {uri!r} has no URI template variables, but the "
                        f"handler declares parameters {func_params}. Add matching "
                        f"{{...}} variables to the URI or remove the parameters."
                    )
                if context_param is not None:
                    raise ValueError(
                        f"Resource {uri!r} has no URI template variables, but the "
                        f"handler declares a Context parameter. Context injection "
                        f"for static resources is not supported. "
                        f"Add a template variable to the URI or remove the "
                        f"Context parameter."
                    )
                # Register as regular resource
                resource = FunctionResource.from_function(
                    fn=fn,
                    uri=uri,
                    name=name,
                    title=title,
                    description=description,
                    mime_type=mime_type,
                    icons=icons,
                    annotations=annotations,
                    meta=meta,
                )
                self.add_resource(resource)
            return fn

        return decorator

    def add_prompt(self, prompt: Prompt) -> None:
        """Add a prompt to the server.

        Args:
            prompt: A Prompt instance to add
        """
        self._prompt_manager.add_prompt(prompt)

    def remove_prompt(self, name: str) -> None:
        """Remove a prompt from the server by name.

        Args:
            name: The name of the prompt to remove

        Raises:
            ValueError: If the prompt does not exist
        """
        self._prompt_manager.remove_prompt(name)

    def prompt(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        icons: list[Icon] | None = None,
    ) -> Callable[[_CallableT], _CallableT]:
        """Decorator to register a prompt.

        The function returns the prompt messages (a string, `Message`, dict,
        or a sequence of these), or an `InputRequiredResult` to request
        client input first (the 2026-07-28 multi-round-trip flow — read
        `ctx.input_responses` on the retry).

        Args:
            name: Optional name for the prompt (defaults to function name)
            title: Optional human-readable title for the prompt
            description: Optional description of what the prompt does
            icons: Optional list of icons for the prompt

        Example:
            ```python
            @server.prompt()
            def analyze_table(table_name: str) -> list[Message]:
                schema = read_table_schema(table_name)
                return [
                    {
                        "role": "user",
                        "content": f"Analyze this schema:\n{schema}"
                    }
                ]

            @server.prompt()
            async def analyze_file(path: str) -> list[Message]:
                content = await read_file(path)
                return [
                    {
                        "role": "user",
                        "content": {
                            "type": "resource",
                            "resource": {
                                "uri": f"file://{path}",
                                "text": content
                            }
                        }
                    }
                ]
            ```
        """
        # Check if user passed function directly instead of calling decorator
        if callable(name):
            raise TypeError(
                "The @prompt decorator was used incorrectly. "
                "Did you forget to call it? Use @prompt() instead of @prompt"
            )

        def decorator(func: _CallableT) -> _CallableT:
            prompt = Prompt.from_function(func, name=name, title=title, description=description, icons=icons)
            self.add_prompt(prompt)
            return func

        return decorator

    def custom_route(
        self,
        path: str,
        methods: list[str],
        name: str | None = None,
        include_in_schema: bool = True,
    ):
        """Decorator to register a custom HTTP route on the MCP server.

        Allows adding arbitrary HTTP endpoints outside the standard MCP protocol,
        which can be useful for OAuth callbacks, health checks, or admin APIs.
        The handler function must be an async function that accepts a Starlette
        Request and returns a Response.

        Routes using this decorator will not require authorization. It is intended
        for uses that are either a part of authorization flows or intended to be
        public such as health check endpoints.

        Args:
            path: URL path for the route (e.g., "/oauth/callback")
            methods: List of HTTP methods to support (e.g., ["GET", "POST"])
            name: Optional name for the route (to reference this route with
                  Starlette's reverse URL lookup feature)
            include_in_schema: Whether to include in OpenAPI schema, defaults to True

        Example:
            ```python
            @server.custom_route("/health", methods=["GET"])
            async def health_check(request: Request) -> Response:
                return JSONResponse({"status": "ok"})
            ```
        """

        def decorator(
            func: Callable[[Request], Awaitable[Response]],
        ) -> Callable[[Request], Awaitable[Response]]:
            self._custom_starlette_routes.append(
                Route(path, endpoint=func, methods=methods, name=name, include_in_schema=include_in_schema)
            )
            return func

        return decorator

    async def run_stdio_async(
        self,
        *,
        stdin: anyio.AsyncFile[str] | None = None,
        stdout: anyio.AsyncFile[str] | None = None,
    ) -> None:
        """Run the server using stdio transport.

        Args:
            stdin: Async text stream to read JSON-RPC lines from. When ``None``,
                uses the process stdin (see :func:`mcp.server.stdio.stdio_server`).
            stdout: Async text stream to write JSON-RPC lines to. When ``None``,
                uses the process stdout.

        Custom streams are useful when the process ``sys.stdout`` / ``sys.stdin``
        must be redirected (for example so logging or subprocess output does not
        corrupt the MCP JSON-RPC stream on fd 1).
        """
        async with stdio_server(stdin=stdin, stdout=stdout) as (read_stream, write_stream):
            await self._lowlevel_server.run(
                read_stream,
                write_stream,
                self._lowlevel_server.create_initialization_options(),
            )

    async def run_sse_async(  # pragma: no cover
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        sse_path: str = "/sse",
        message_path: str = "/messages/",
        transport_security: TransportSecuritySettings | None = None,
    ) -> None:
        """Run the server using SSE transport."""
        import uvicorn

        starlette_app = self.sse_app(
            sse_path=sse_path,
            message_path=message_path,
            transport_security=transport_security,
            host=host,
        )

        config = uvicorn.Config(
            starlette_app,
            host=host,
            port=port,
            log_level=self.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def run_streamable_http_async(  # pragma: no cover
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        streamable_http_path: str = "/mcp",
        json_response: bool = False,
        stateless_http: bool = False,
        event_store: EventStore | None = None,
        retry_interval: int | None = None,
        transport_security: TransportSecuritySettings | None = None,
    ) -> None:
        """Run the server using StreamableHTTP transport."""
        import uvicorn

        starlette_app = self.streamable_http_app(
            streamable_http_path=streamable_http_path,
            json_response=json_response,
            stateless_http=stateless_http,
            event_store=event_store,
            retry_interval=retry_interval,
            transport_security=transport_security,
            host=host,
        )

        config = uvicorn.Config(
            starlette_app,
            host=host,
            port=port,
            log_level=self.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    def sse_app(
        self,
        *,
        sse_path: str = "/sse",
        message_path: str = "/messages/",
        transport_security: TransportSecuritySettings | None = None,
        host: str = "127.0.0.1",
    ) -> Starlette:
        """Return an instance of the SSE server app."""
        # Auto-enable DNS rebinding protection for localhost (IPv4 and IPv6)
        if transport_security is None and host in ("127.0.0.1", "localhost", "::1"):
            transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
            )

        sse = SseServerTransport(message_path, security_settings=transport_security)

        async def handle_sse(scope: Scope, receive: Receive, send: Send):  # pragma: no cover
            # Add client ID from auth context into request context if available

            async with sse.connect_sse(scope, receive, send) as streams:
                await self._lowlevel_server.run(
                    streams[0], streams[1], self._lowlevel_server.create_initialization_options()
                )
            return Response()

        # Create routes
        routes: list[Route | Mount] = []
        middleware: list[Middleware] = []
        required_scopes: list[str] = []

        # Set up auth if configured
        if self.settings.auth:  # pragma: no cover
            required_scopes = self.settings.auth.required_scopes or []

            # Add auth middleware if token verifier is available
            if self._token_verifier:
                middleware = [
                    # extract auth info from request (but do not require it)
                    Middleware(
                        AuthenticationMiddleware,
                        backend=BearerAuthBackend(self._token_verifier),
                    ),
                    # Add the auth context middleware to store
                    # authenticated user in a contextvar
                    Middleware(AuthContextMiddleware),
                ]

            # Add auth endpoints if auth server provider is configured
            if self._auth_server_provider:
                from mcp.server.auth.routes import create_auth_routes

                routes.extend(
                    create_auth_routes(
                        provider=self._auth_server_provider,
                        issuer_url=self.settings.auth.issuer_url,
                        service_documentation_url=self.settings.auth.service_documentation_url,
                        client_registration_options=self.settings.auth.client_registration_options,
                        revocation_options=self.settings.auth.revocation_options,
                        identity_assertion_enabled=self.settings.auth.identity_assertion_enabled,
                    )
                )

        # When auth is configured, require authentication
        if self._token_verifier:  # pragma: no cover
            # Determine resource metadata URL
            resource_metadata_url = None
            if self.settings.auth and self.settings.auth.resource_server_url:
                from mcp.server.auth.routes import build_resource_metadata_url

                # Build compliant metadata URL for WWW-Authenticate header
                resource_metadata_url = build_resource_metadata_url(self.settings.auth.resource_server_url)

            # Auth is enabled, wrap the endpoints with RequireAuthMiddleware
            routes.append(
                Route(
                    sse_path,
                    endpoint=RequireAuthMiddleware(handle_sse, required_scopes, resource_metadata_url),
                    methods=["GET"],
                )
            )
            routes.append(
                Mount(
                    message_path,
                    app=RequireAuthMiddleware(sse.handle_post_message, required_scopes, resource_metadata_url),
                )
            )
        else:
            # Auth is disabled, no need for RequireAuthMiddleware
            # Since handle_sse is an ASGI app, we need to create a compatible endpoint
            async def sse_endpoint(request: Request) -> Response:  # pragma: no cover
                # Convert the Starlette request to ASGI parameters
                return await handle_sse(request.scope, request.receive, request._send)  # type: ignore[reportPrivateUsage]

            routes.append(
                Route(
                    sse_path,
                    endpoint=sse_endpoint,
                    methods=["GET"],
                )
            )
            routes.append(
                Mount(
                    message_path,
                    app=sse.handle_post_message,
                )
            )
        # Add protected resource metadata endpoint if configured as RS
        if self.settings.auth and self.settings.auth.resource_server_url:  # pragma: no cover
            from mcp.server.auth.routes import create_protected_resource_routes

            routes.extend(
                create_protected_resource_routes(
                    resource_url=self.settings.auth.resource_server_url,
                    authorization_servers=[self.settings.auth.issuer_url],
                    scopes_supported=self.settings.auth.required_scopes,
                )
            )

        # mount these routes last, so they have the lowest route matching precedence
        routes.extend(self._custom_starlette_routes)

        # Create Starlette app with routes and middleware
        return Starlette(debug=self.settings.debug, routes=routes, middleware=middleware)

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
    ) -> Starlette:
        """Return an instance of the StreamableHTTP server app."""
        return self._lowlevel_server.streamable_http_app(
            streamable_http_path=streamable_http_path,
            json_response=json_response,
            stateless_http=stateless_http,
            event_store=event_store,
            retry_interval=retry_interval,
            transport_security=transport_security,
            host=host,
            auth=self.settings.auth,
            token_verifier=self._token_verifier,
            auth_server_provider=self._auth_server_provider,
            custom_starlette_routes=self._custom_starlette_routes,
            debug=self.settings.debug,
        )

    async def list_prompts(self) -> list[MCPPrompt]:
        """List all available prompts."""
        prompts = self._prompt_manager.list_prompts()
        return [
            MCPPrompt(
                name=prompt.name,
                title=prompt.title,
                description=prompt.description,
                arguments=[
                    MCPPromptArgument(
                        name=arg.name,
                        description=arg.description,
                        required=arg.required,
                    )
                    for arg in (prompt.arguments or [])
                ],
                icons=prompt.icons,
            )
            for prompt in prompts
        ]

    async def get_prompt(
        self, name: str, arguments: dict[str, Any] | None = None, context: Context[LifespanResultT, Any] | None = None
    ) -> GetPromptResult | InputRequiredResult:
        """Get a prompt by name with arguments.

        An `InputRequiredResult` returned by the prompt function is passed
        through unchanged (the 2026-07-28 multi-round-trip flow); the retry's
        answers arrive on `ctx.input_responses`, with `ctx.request_state`
        carrying the echoed opaque state.
        """
        if context is None:
            context = Context(mcp_server=self, subscriptions=self._subscriptions)
        try:
            prompt = self._prompt_manager.get_prompt(name)
            if not prompt:
                raise ValueError(f"Unknown prompt: {name}")

            rendered = await prompt.render(arguments, context)
            if isinstance(rendered, InputRequiredResult):
                return rendered

            return GetPromptResult(
                description=prompt.description,
                messages=pydantic_core.to_jsonable_python(rendered),
            )
        except MCPError:
            raise
        except Exception as e:
            logger.exception(f"Error getting prompt {name}")
            raise ValueError(str(e)) from e


def _version_gated(method: MethodBinding) -> RequestHandler:
    """Wrap a method handler so a request at a disallowed protocol version is rejected.

    The low-level `_request_handlers` dict is keyed by method only, so per-version
    scoping is enforced here rather than at the runner's boundary table.
    """
    versions = method.protocol_versions
    assert versions is not None

    async def gated(ctx: ServerRequestContext[Any, Any], params: Any) -> HandlerResult:
        if ctx.protocol_version not in versions:
            raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method.method)
        return await method.handler(ctx, params)

    return gated


def require_client_extension(ctx: ServerRequestContext[Any, Any], identifier: str) -> None:
    """Assert the connected client declared support for `identifier`.

    Call this from an extension's handler or `intercept_tool_call` before
    offering extension-specific behaviour. Raises `MCPError` with the
    `-32021` (missing required client capability) code and a
    `requiredCapabilities` payload when the client did not declare the
    extension, per SEP-2133.

    Args:
        ctx: The current request context.
        identifier: The extension identifier the client must have declared.

    Raises:
        MCPError: With code `MISSING_REQUIRED_CLIENT_CAPABILITY` if the client
            did not advertise `identifier`.
    """
    client_params = ctx.session.client_params
    declared = client_params.capabilities.extensions if client_params else None
    if not declared or identifier not in declared:
        data = MissingRequiredClientCapabilityErrorData(
            required_capabilities=ClientCapabilities(extensions={identifier: {}})
        )
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message=f"Client did not declare required extension {identifier!r}",
            data=data.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
