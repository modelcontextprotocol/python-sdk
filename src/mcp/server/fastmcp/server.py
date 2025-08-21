"""FastMCP - A more ergonomic interface for MCP servers."""

from __future__ import annotations as _annotations

import inspect
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Generic, Literal

import anyio
import pydantic_core
from pydantic import BaseModel
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
from mcp.server.elicitation import ElicitationResult, ElicitSchemaModelT, elicit_with_validation
from mcp.server.fastmcp.exceptions import ResourceError
from mcp.server.fastmcp.prompts import Prompt, PromptManager
from mcp.server.fastmcp.resources import FunctionResource, Resource, ResourceManager
from mcp.server.fastmcp.tools import Tool, ToolManager
from mcp.server.fastmcp.utilities.logging import configure_logging, get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.lowlevel.server import Server as MCPServer
from mcp.server.lowlevel.server import lifespan as default_lifespan
from mcp.server.session import ServerSession, ServerSessionT
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.context import LifespanContextT, RequestContext, RequestT
from mcp.types import AnyFunction, ContentBlock, GetPromptResult, ToolAnnotations
from mcp.types import Prompt as MCPPrompt
from mcp.types import PromptArgument as MCPPromptArgument
from mcp.types import Resource as MCPResource
from mcp.types import ResourceTemplate as MCPResourceTemplate
from mcp.types import Tool as MCPTool

logger = get_logger(__name__)


class Settings(BaseSettings, Generic[LifespanResultT]):
    """FastMCP server settings.

    All settings can be configured via environment variables with the prefix FASTMCP_.
    For example, FASTMCP_DEBUG=true will set debug=True.
    """

    model_config = SettingsConfigDict(
        env_prefix="FASTMCP_",
        env_file=".env",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        extra="ignore",
    )

    # Server settings
    debug: bool
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    # HTTP settings
    host: str
    port: int
    mount_path: str
    sse_path: str
    message_path: str
    streamable_http_path: str

    # StreamableHTTP settings
    json_response: bool
    stateless_http: bool
    """Define if the server should create a new transport per request."""

    # resource settings
    warn_on_duplicate_resources: bool

    # tool settings
    warn_on_duplicate_tools: bool

    # prompt settings
    warn_on_duplicate_prompts: bool

    # TODO(Marcelo): Investigate if this is used. If it is, it's probably a good idea to remove it.
    dependencies: list[str]
    """A list of dependencies to install in the server environment."""

    lifespan: Callable[[FastMCP[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None
    """A async context manager that will be called when the server is started."""

    auth: AuthSettings | None

    # Transport security settings (DNS rebinding protection)
    transport_security: TransportSecuritySettings | None


def lifespan_wrapper(
    app: FastMCP[LifespanResultT],
    lifespan: Callable[[FastMCP[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]],
) -> Callable[[MCPServer[LifespanResultT, Request]], AbstractAsyncContextManager[LifespanResultT]]:
    @asynccontextmanager
    async def wrap(_: MCPServer[LifespanResultT, Request]) -> AsyncIterator[LifespanResultT]:
        async with lifespan(app) as context:
            yield context

    return wrap


class FastMCP(Generic[LifespanResultT]):
    """A high-level ergonomic interface for creating MCP servers.

    FastMCP provides a decorator-based API for building MCP servers with automatic
    parameter validation, structured output support, and built-in transport handling.
    It supports stdio, SSE, and Streamable HTTP transports out of the box.

    Features include automatic validation using Pydantic, structured output conversion,
    context injection for MCP capabilities, lifespan management, multiple transport
    support, and built-in OAuth 2.1 authentication.

    Args:
        name: Human-readable name for the server. If None, defaults to "FastMCP"
        instructions: Optional instructions/description for the server
        auth_server_provider: OAuth authorization server provider for authentication
        token_verifier: Token verifier for validating OAuth tokens
        event_store: Event store for Streamable HTTP transport persistence
        tools: Pre-configured tools to register with the server
        debug: Enable debug mode for additional logging
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        host: Host address for HTTP transports
        port: Port number for HTTP transports
        mount_path: Base mount path for SSE transport
        sse_path: Path for SSE endpoint
        message_path: Path for message endpoint
        streamable_http_path: Path for Streamable HTTP endpoint
        json_response: Whether to use JSON responses instead of SSE for Streamable HTTP
        stateless_http: Whether to operate in stateless mode for Streamable HTTP
        warn_on_duplicate_resources: Whether to warn when duplicate resources are registered
        warn_on_duplicate_tools: Whether to warn when duplicate tools are registered
        warn_on_duplicate_prompts: Whether to warn when duplicate prompts are registered
        dependencies: List of package dependencies (currently unused)
        lifespan: Async context manager for server startup/shutdown lifecycle
        auth: Authentication settings for OAuth 2.1 support
        transport_security: Transport security settings

    Examples:
        Basic server creation:

        ```python
        from mcp.server.fastmcp import FastMCP

        # Create a server
        mcp = FastMCP("My Server")

        # Add a tool
        @mcp.tool()
        def add_numbers(a: int, b: int) -> int:
            \"\"\"Add two numbers together.\"\"\"
            return a + b

        # Add a resource
        @mcp.resource("greeting://{name}")
        def get_greeting(name: str) -> str:
            \"\"\"Get a personalized greeting.\"\"\"
            return f"Hello, {name}!"

        # Run the server
        if __name__ == "__main__":
            mcp.run()
        ```

        Server with authentication:

        ```python
        from mcp.server.auth.settings import AuthSettings
        from pydantic import AnyHttpUrl

        mcp = FastMCP(
            "Protected Server",
            auth=AuthSettings(
                issuer_url=AnyHttpUrl("https://auth.example.com"),
                resource_server_url=AnyHttpUrl("http://localhost:8000"),
                required_scopes=["read", "write"]
            )
        )
        ```
    """

    def __init__(
        self,
        name: str | None = None,
        instructions: str | None = None,
        auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
        token_verifier: TokenVerifier | None = None,
        event_store: EventStore | None = None,
        *,
        tools: list[Tool] | None = None,
        debug: bool = False,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
        host: str = "127.0.0.1",
        port: int = 8000,
        mount_path: str = "/",
        sse_path: str = "/sse",
        message_path: str = "/messages/",
        streamable_http_path: str = "/mcp",
        json_response: bool = False,
        stateless_http: bool = False,
        warn_on_duplicate_resources: bool = True,
        warn_on_duplicate_tools: bool = True,
        warn_on_duplicate_prompts: bool = True,
        dependencies: Collection[str] = (),
        lifespan: Callable[[FastMCP[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None = None,
        auth: AuthSettings | None = None,
        transport_security: TransportSecuritySettings | None = None,
    ):
        self.settings = Settings(
            debug=debug,
            log_level=log_level,
            host=host,
            port=port,
            mount_path=mount_path,
            sse_path=sse_path,
            message_path=message_path,
            streamable_http_path=streamable_http_path,
            json_response=json_response,
            stateless_http=stateless_http,
            warn_on_duplicate_resources=warn_on_duplicate_resources,
            warn_on_duplicate_tools=warn_on_duplicate_tools,
            warn_on_duplicate_prompts=warn_on_duplicate_prompts,
            dependencies=list(dependencies),
            lifespan=lifespan,
            auth=auth,
            transport_security=transport_security,
        )

        self._mcp_server = MCPServer(
            name=name or "FastMCP",
            instructions=instructions,
            # TODO(Marcelo): It seems there's a type mismatch between the lifespan type from an FastMCP and Server.
            # We need to create a Lifespan type that is a generic on the server type, like Starlette does.
            lifespan=(lifespan_wrapper(self, self.settings.lifespan) if self.settings.lifespan else default_lifespan),  # type: ignore
        )
        self._tool_manager = ToolManager(tools=tools, warn_on_duplicate_tools=self.settings.warn_on_duplicate_tools)
        self._resource_manager = ResourceManager(warn_on_duplicate_resources=self.settings.warn_on_duplicate_resources)
        self._prompt_manager = PromptManager(warn_on_duplicate_prompts=self.settings.warn_on_duplicate_prompts)
        # Validate auth configuration
        if self.settings.auth is not None:
            if auth_server_provider and token_verifier:
                raise ValueError("Cannot specify both auth_server_provider and token_verifier")
            if not auth_server_provider and not token_verifier:
                raise ValueError("Must specify either auth_server_provider or token_verifier when auth is enabled")
        else:
            if auth_server_provider or token_verifier:
                raise ValueError("Cannot specify auth_server_provider or token_verifier without auth settings")

        self._auth_server_provider = auth_server_provider
        self._token_verifier = token_verifier

        # Create token verifier from provider if needed (backwards compatibility)
        if auth_server_provider and not token_verifier:
            self._token_verifier = ProviderTokenVerifier(auth_server_provider)
        self._event_store = event_store
        self._custom_starlette_routes: list[Route] = []
        self.dependencies = self.settings.dependencies
        self._session_manager: StreamableHTTPSessionManager | None = None

        # Set up MCP protocol handlers
        self._setup_handlers()

        # Configure logging
        configure_logging(self.settings.log_level)

    @property
    def name(self) -> str:
        return self._mcp_server.name

    @property
    def instructions(self) -> str | None:
        return self._mcp_server.instructions

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        """Get the StreamableHTTP session manager.

        This is exposed to enable advanced use cases like mounting multiple
        FastMCP servers in a single FastAPI application.

        Raises:
            RuntimeError: If called before streamable_http_app() has been called.
        """
        if self._session_manager is None:
            raise RuntimeError(
                "Session manager can only be accessed after"
                "calling streamable_http_app()."
                "The session manager is created lazily"
                "to avoid unnecessary initialization."
            )
        return self._session_manager

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        mount_path: str | None = None,
    ) -> None:
        """Run the FastMCP server. This is a synchronous function.

        Args:
            transport: Transport protocol to use ("stdio", "sse", or "streamable-http")
            mount_path: Optional mount path for SSE transport
        """
        TRANSPORTS = Literal["stdio", "sse", "streamable-http"]
        if transport not in TRANSPORTS.__args__:  # type: ignore
            raise ValueError(f"Unknown transport: {transport}")

        match transport:
            case "stdio":
                anyio.run(self.run_stdio_async)
            case "sse":
                anyio.run(lambda: self.run_sse_async(mount_path))
            case "streamable-http":
                anyio.run(self.run_streamable_http_async)

    def _setup_handlers(self) -> None:
        """Set up core MCP protocol handlers."""
        self._mcp_server.list_tools()(self.list_tools)
        # Note: we disable the lowlevel server's input validation.
        # FastMCP does ad hoc conversion of incoming data before validating -
        # for now we preserve this for backwards compatibility.
        self._mcp_server.call_tool(validate_input=False)(self.call_tool)
        self._mcp_server.list_resources()(self.list_resources)
        self._mcp_server.read_resource()(self.read_resource)
        self._mcp_server.list_prompts()(self.list_prompts)
        self._mcp_server.get_prompt()(self.get_prompt)
        self._mcp_server.list_resource_templates()(self.list_resource_templates)

    async def list_tools(self) -> list[MCPTool]:
        """List all available tools."""
        tools = self._tool_manager.list_tools()
        return [
            MCPTool(
                name=info.name,
                title=info.title,
                description=info.description,
                inputSchema=info.parameters,
                outputSchema=info.output_schema,
                annotations=info.annotations,
            )
            for info in tools
        ]

    def get_context(self) -> Context[ServerSession, LifespanResultT, Request]:
        """Get the current request context when automatic injection isn't available.

        This method provides access to the current [`Context`][mcp.server.fastmcp.Context]
        object when you can't rely on FastMCP's automatic parameter injection. It's
        primarily useful in helper functions, callbacks, or other scenarios where
        the context isn't automatically provided via function parameters.

        In most cases, you should prefer automatic context injection by declaring
        a Context parameter in your tool/resource functions. Use this method only
        when you need context access from code that isn't directly called by FastMCP.

        You might call this method directly in:

        - **Helper functions**

            ```python
            mcp = FastMCP(name="example")

            async def log_operation(operation: str):
                # Get context when it's not injected
                ctx = mcp.get_context()
                await ctx.info(f"Performing operation: {operation}")

            @mcp.tool()
            async def main_tool(data: str) -> str:
                await log_operation("data_processing")  # Helper needs context
                return process_data(data)
            ```

        - **Callbacks** and **event handlers** when context is needed in async callbacks

            ```python
            async def progress_callback(current: int, total: int):
                ctx = mcp.get_context()  # Access context in callback
                await ctx.report_progress(current, total)

            @mcp.tool()
            async def long_operation(data: str) -> str:
                return await process_with_callback(data, progress_callback)
            ```

        - **Class methods** when context is needed in class-based code

            ```python
            class DataProcessor:
                def __init__(self, mcp_server: FastMCP):
                    self.mcp = mcp_server

                async def process_chunk(self, chunk: str) -> str:
                    ctx = self.mcp.get_context()  # Get context in method
                    await ctx.debug(f"Processing chunk of size {len(chunk)}")
                    return processed_chunk

            processor = DataProcessor(mcp)

            @mcp.tool()
            async def process_data(data: str) -> str:
                return await processor.process_chunk(data)
            ```

        Returns:
            [`Context`][mcp.server.fastmcp.Context] object for the current request
            with access to all MCP capabilities including logging, progress reporting,
            user interaction, and session access.

        Raises:
            LookupError: If called outside of a request context (e.g., during server
                initialization, shutdown, or from code not handling a client request).

        Note:
            **Prefer automatic injection**: In most cases, declare a Context parameter
            in your function signature instead of calling this method:

            ```python
            # Preferred approach
            @mcp.tool()
            async def my_tool(data: str, ctx: Context) -> str:
                await ctx.info("Processing data")
                return result

            # Only use get_context() when injection isn't available
            async def helper_function():
                ctx = mcp.get_context()
                await ctx.info("Helper called")
            ```
        """
        try:
            request_context = self._mcp_server.request_context
        except LookupError:
            request_context = None
        return Context(request_context=request_context, fastmcp=self)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        """Call a registered tool by name with the provided arguments.

        Args:
            name: Name of the tool to call
            arguments: Dictionary of arguments to pass to the tool

        Returns:
            Tool execution result, either as content blocks or structured data

        Raises:
            ToolError: If the tool is not found or execution fails
            ValidationError: If the arguments don't match the tool's schema
        """
        context = self.get_context()
        return await self._tool_manager.call_tool(name, arguments, context=context, convert_result=True)

    async def list_resources(self) -> list[MCPResource]:
        """List all available resources registered with this server.

        Returns:
            List of MCP Resource objects containing URI, name, description, and MIME type
            information for each registered resource.
        """

        resources = self._resource_manager.list_resources()
        return [
            MCPResource(
                uri=resource.uri,
                name=resource.name or "",
                title=resource.title,
                description=resource.description,
                mimeType=resource.mime_type,
            )
            for resource in resources
        ]

    async def list_resource_templates(self) -> list[MCPResourceTemplate]:
        """List all available resource templates registered with this server.

        Resource templates define URI patterns that can be dynamically resolved
        with different parameters to access multiple related resources.

        Returns:
            List of MCP ResourceTemplate objects containing URI templates, names,
            and descriptions for each registered resource template.
        """
        templates = self._resource_manager.list_templates()
        return [
            MCPResourceTemplate(
                uriTemplate=template.uri_template,
                name=template.name,
                title=template.title,
                description=template.description,
            )
            for template in templates
        ]

    async def read_resource(self, uri: AnyUrl | str) -> Iterable[ReadResourceContents]:
        """Read the contents of a resource by its URI.

        Args:
            uri: The URI of the resource to read

        Returns:
            Iterable of ReadResourceContents containing the resource data

        Raises:
            ResourceError: If the resource is not found or cannot be read
        """

        resource = await self._resource_manager.get_resource(uri)
        if not resource:
            raise ResourceError(f"Unknown resource: {uri}")

        try:
            content = await resource.read()
            return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
        except Exception as e:
            logger.exception(f"Error reading resource {uri}")
            raise ResourceError(str(e))

    def add_tool(
        self,
        fn: AnyFunction,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
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
            structured_output: Controls whether the tool's output is structured or unstructured
                - If None, auto-detects based on the function's return type annotation
                - If True, unconditionally creates a structured tool (return type annotation permitting)
                - If False, unconditionally creates an unstructured tool
        """
        self._tool_manager.add_tool(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
        )

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Decorator to register a tool.

        Tools can optionally request a Context object by adding a parameter with the
        Context type annotation. The context provides access to MCP capabilities like
        logging, progress reporting, and resource access.

        Args:
            name: Optional name for the tool (defaults to function name)
            title: Optional human-readable title for the tool
            description: Optional description of what the tool does
            annotations: Optional ToolAnnotations providing additional tool information
            structured_output: Controls whether the tool's output is structured or unstructured
                - If None, auto-detects based on the function's return type annotation
                - If True, unconditionally creates a structured tool (return type annotation permitting)
                - If False, unconditionally creates an unstructured tool

        Example:

        ```python
        @server.tool()
        def my_tool(x: int) -> str:
            return str(x)

        @server.tool()
        def tool_with_context(x: int, ctx: Context) -> str:
            ctx.info(f"Processing {x}")
            return str(x)

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

        def decorator(fn: AnyFunction) -> AnyFunction:
            self.add_tool(
                fn,
                name=name,
                title=title,
                description=description,
                annotations=annotations,
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
        return self._mcp_server.completion()

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
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Decorator to register a function as a resource.

        The function will be called when the resource is read to generate its content.
        The function can return:
        - str for text content
        - bytes for binary content
        - other types will be converted to JSON

        If the URI contains parameters (e.g. "resource://{param}") or the function
        has parameters, it will be registered as a template resource.

        Args:
            uri: URI for the resource (e.g. "resource://my-resource" or "resource://{param}")
            name: Optional name for the resource
            title: Optional human-readable title for the resource
            description: Optional description of the resource
            mime_type: Optional MIME type for the resource

        Example:

        ```python
        @server.resource("resource://my-resource")
        def get_data() -> str:
            return "Hello, world!"

        @server.resource("resource://my-resource")
        async get_data() -> str:
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
        """
        # Check if user passed function directly instead of calling decorator
        if callable(uri):
            raise TypeError(
                "The @resource decorator was used incorrectly. "
                "Did you forget to call it? Use @resource('uri') instead of @resource"
            )

        def decorator(fn: AnyFunction) -> AnyFunction:
            # Check if this should be a template
            has_uri_params = "{" in uri and "}" in uri
            has_func_params = bool(inspect.signature(fn).parameters)

            if has_uri_params or has_func_params:
                # Validate that URI params match function params
                uri_params = set(re.findall(r"{(\w+)}", uri))
                func_params = set(inspect.signature(fn).parameters.keys())

                if uri_params != func_params:
                    raise ValueError(
                        f"Mismatch between URI parameters {uri_params} and function parameters {func_params}"
                    )

                # Register as template
                self._resource_manager.add_template(
                    fn=fn,
                    uri_template=uri,
                    name=name,
                    title=title,
                    description=description,
                    mime_type=mime_type,
                )
            else:
                # Register as regular resource
                resource = FunctionResource.from_function(
                    fn=fn,
                    uri=uri,
                    name=name,
                    title=title,
                    description=description,
                    mime_type=mime_type,
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

    def prompt(
        self, name: str | None = None, title: str | None = None, description: str | None = None
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Decorator to register a prompt.

        Args:
            name: Optional name for the prompt (defaults to function name)
            title: Optional human-readable title for the prompt
            description: Optional description of what the prompt does

        Examples:

        ```python
        @server.prompt()
        def analyze_table(table_name: str) -> list[Message]:
            schema = read_table_schema(table_name)
            return [
                {
                    "role": "user",
                    "content": f"Analyze this schema: {schema}"
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

        def decorator(func: AnyFunction) -> AnyFunction:
            prompt = Prompt.from_function(func, name=name, title=title, description=description)
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
        """
        Decorator to register a custom HTTP route on the FastMCP server.

        Allows adding arbitrary HTTP endpoints outside the standard MCP protocol,
        which can be useful for OAuth callbacks, health checks, or admin APIs.
        The handler function must be an async function that accepts a Starlette
        Request and returns a Response.

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
                Route(
                    path,
                    endpoint=func,
                    methods=methods,
                    name=name,
                    include_in_schema=include_in_schema,
                )
            )
            return func

        return decorator

    async def run_stdio_async(self) -> None:
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self._mcp_server.run(
                read_stream,
                write_stream,
                self._mcp_server.create_initialization_options(),
            )

    async def run_sse_async(self, mount_path: str | None = None) -> None:
        """Run the server using SSE transport."""
        import uvicorn

        starlette_app = self.sse_app(mount_path)

        config = uvicorn.Config(
            starlette_app,
            host=self.settings.host,
            port=self.settings.port,
            log_level=self.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def run_streamable_http_async(self) -> None:
        """Run the server using StreamableHTTP transport."""
        import uvicorn

        starlette_app = self.streamable_http_app()

        config = uvicorn.Config(
            starlette_app,
            host=self.settings.host,
            port=self.settings.port,
            log_level=self.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    def _normalize_path(self, mount_path: str, endpoint: str) -> str:
        """
        Combine mount path and endpoint to return a normalized path.

        Args:
            mount_path: The mount path (e.g. "/github" or "/")
            endpoint: The endpoint path (e.g. "/messages/")

        Returns:
            Normalized path (e.g. "/github/messages/")
        """
        # Special case: root path
        if mount_path == "/":
            return endpoint

        # Remove trailing slash from mount path
        if mount_path.endswith("/"):
            mount_path = mount_path[:-1]

        # Ensure endpoint starts with slash
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        # Combine paths
        return mount_path + endpoint

    def sse_app(self, mount_path: str | None = None) -> Starlette:
        """Return an instance of the SSE server app."""
        from starlette.middleware import Middleware
        from starlette.routing import Mount, Route

        # Update mount_path in settings if provided
        if mount_path is not None:
            self.settings.mount_path = mount_path

        # Create normalized endpoint considering the mount path
        normalized_message_endpoint = self._normalize_path(self.settings.mount_path, self.settings.message_path)

        # Set up auth context and dependencies

        sse = SseServerTransport(
            normalized_message_endpoint,
            security_settings=self.settings.transport_security,
        )

        async def handle_sse(scope: Scope, receive: Receive, send: Send):
            # Add client ID from auth context into request context if available

            async with sse.connect_sse(
                scope,
                receive,
                send,
            ) as streams:
                await self._mcp_server.run(
                    streams[0],
                    streams[1],
                    self._mcp_server.create_initialization_options(),
                )
            return Response()

        # Create routes
        routes: list[Route | Mount] = []
        middleware: list[Middleware] = []
        required_scopes = []

        # Set up auth if configured
        if self.settings.auth:
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
                    )
                )

        # When auth is configured, require authentication
        if self._token_verifier:
            # Determine resource metadata URL
            resource_metadata_url = None
            if self.settings.auth and self.settings.auth.resource_server_url:
                from pydantic import AnyHttpUrl

                resource_metadata_url = AnyHttpUrl(
                    str(self.settings.auth.resource_server_url).rstrip("/") + "/.well-known/oauth-protected-resource"
                )

            # Auth is enabled, wrap the endpoints with RequireAuthMiddleware
            routes.append(
                Route(
                    self.settings.sse_path,
                    endpoint=RequireAuthMiddleware(handle_sse, required_scopes, resource_metadata_url),
                    methods=["GET"],
                )
            )
            routes.append(
                Mount(
                    self.settings.message_path,
                    app=RequireAuthMiddleware(sse.handle_post_message, required_scopes, resource_metadata_url),
                )
            )
        else:
            # Auth is disabled, no need for RequireAuthMiddleware
            # Since handle_sse is an ASGI app, we need to create a compatible endpoint
            async def sse_endpoint(request: Request) -> Response:
                # Convert the Starlette request to ASGI parameters
                return await handle_sse(request.scope, request.receive, request._send)  # type: ignore[reportPrivateUsage]

            routes.append(
                Route(
                    self.settings.sse_path,
                    endpoint=sse_endpoint,
                    methods=["GET"],
                )
            )
            routes.append(
                Mount(
                    self.settings.message_path,
                    app=sse.handle_post_message,
                )
            )
        # Add protected resource metadata endpoint if configured as RS
        if self.settings.auth and self.settings.auth.resource_server_url:
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

    def streamable_http_app(self) -> Starlette:
        """Return an instance of the StreamableHTTP server app."""
        from starlette.middleware import Middleware

        # Create session manager on first call (lazy initialization)
        if self._session_manager is None:
            self._session_manager = StreamableHTTPSessionManager(
                app=self._mcp_server,
                event_store=self._event_store,
                json_response=self.settings.json_response,
                stateless=self.settings.stateless_http,  # Use the stateless setting
                security_settings=self.settings.transport_security,
            )

        # Create the ASGI handler
        streamable_http_app = StreamableHTTPASGIApp(self._session_manager)

        # Create routes
        routes: list[Route | Mount] = []
        middleware: list[Middleware] = []
        required_scopes = []

        # Set up auth if configured
        if self.settings.auth:
            required_scopes = self.settings.auth.required_scopes or []

            # Add auth middleware if token verifier is available
            if self._token_verifier:
                middleware = [
                    Middleware(
                        AuthenticationMiddleware,
                        backend=BearerAuthBackend(self._token_verifier),
                    ),
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
                    )
                )

        # Set up routes with or without auth
        if self._token_verifier:
            # Determine resource metadata URL
            resource_metadata_url = None
            if self.settings.auth and self.settings.auth.resource_server_url:
                from pydantic import AnyHttpUrl

                resource_metadata_url = AnyHttpUrl(
                    str(self.settings.auth.resource_server_url).rstrip("/") + "/.well-known/oauth-protected-resource"
                )

            routes.append(
                Route(
                    self.settings.streamable_http_path,
                    endpoint=RequireAuthMiddleware(streamable_http_app, required_scopes, resource_metadata_url),
                )
            )
        else:
            # Auth is disabled, no wrapper needed
            routes.append(
                Route(
                    self.settings.streamable_http_path,
                    endpoint=streamable_http_app,
                )
            )

        # Add protected resource metadata endpoint if configured as RS
        if self.settings.auth and self.settings.auth.resource_server_url:
            from mcp.server.auth.handlers.metadata import ProtectedResourceMetadataHandler
            from mcp.server.auth.routes import cors_middleware
            from mcp.shared.auth import ProtectedResourceMetadata

            protected_resource_metadata = ProtectedResourceMetadata(
                resource=self.settings.auth.resource_server_url,
                authorization_servers=[self.settings.auth.issuer_url],
                scopes_supported=self.settings.auth.required_scopes,
            )
            routes.append(
                Route(
                    "/.well-known/oauth-protected-resource",
                    endpoint=cors_middleware(
                        ProtectedResourceMetadataHandler(protected_resource_metadata).handle,
                        ["GET", "OPTIONS"],
                    ),
                    methods=["GET", "OPTIONS"],
                )
            )

        routes.extend(self._custom_starlette_routes)

        return Starlette(
            debug=self.settings.debug,
            routes=routes,
            middleware=middleware,
            lifespan=lambda app: self.session_manager.run(),
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
            )
            for prompt in prompts
        ]

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        """Get a prompt by name with arguments."""
        try:
            prompt = self._prompt_manager.get_prompt(name)
            if not prompt:
                raise ValueError(f"Unknown prompt: {name}")

            messages = await prompt.render(arguments)

            return GetPromptResult(
                description=prompt.description,
                messages=pydantic_core.to_jsonable_python(messages),
            )
        except Exception as e:
            logger.exception(f"Error getting prompt {name}")
            raise ValueError(str(e))


class StreamableHTTPASGIApp:
    """
    ASGI application for Streamable HTTP server transport.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


class Context(BaseModel, Generic[ServerSessionT, LifespanContextT, RequestT]):
    """High-level context object providing convenient access to MCP capabilities.

    This is FastMCP's user-friendly wrapper around the underlying [`RequestContext`][mcp.shared.context.RequestContext]
    that provides the same functionality with additional convenience methods and better
    ergonomics. It gets automatically injected into FastMCP tool and resource functions
    that declare it in their type hints, eliminating the need to manually access the
    request context.

    The Context object provides access to all MCP capabilities including logging,
    progress reporting, resource reading, user interaction, capability checking, and
    access to the underlying session and request metadata. It's the recommended way
    to interact with MCP functionality in FastMCP applications.

    ## Automatic injection

    Context is automatically injected into functions based on type hints. The parameter
    name can be anything as long as it's annotated with `Context`. The context parameter
    is optional - tools that don't need it can omit it entirely.

    ```python
    from mcp.server.fastmcp import FastMCP, Context

    mcp = FastMCP(name="example")

    @mcp.tool()
    async def simple_tool(data: str) -> str:
        # No context needed
        return f"Processed: {data}"

    @mcp.tool()
    async def advanced_tool(data: str, ctx: Context) -> str:
        # Context automatically injected
        await ctx.info("Starting processing")
        return f"Processed: {data}"
    ```

    ## Relationship to RequestContext

    Context is a thin wrapper around [`RequestContext`][mcp.shared.context.RequestContext]
    that provides the same underlying functionality with additional convenience methods:

    - **Context convenience methods**: `ctx.info()`, `ctx.error()`, `ctx.elicit()`, etc.
    - **Direct RequestContext access**: `ctx.request_context` for low-level operations
    - **Session access**: `ctx.session` for advanced ServerSession functionality
    - **Request metadata**: `ctx.request_id`, access to lifespan context, etc.

    ## Capabilities provided

    **Logging**: Send structured log messages to the client with automatic request linking:

    ```python
    await ctx.debug("Detailed debug information")
    await ctx.info("General status updates")
    await ctx.warning("Important warnings")
    await ctx.error("Error conditions")
    ```

    **Progress reporting**: Keep users informed during long operations:

    ```python
    for i in range(100):
        await ctx.report_progress(i, 100, f"Processing item {i}")
        # ... do work
    ```

    **User interaction**: Collect additional information during tool execution:

    ```python
    class UserPrefs(BaseModel):
        format: str
        detailed: bool

    result = await ctx.elicit("How should I format the output?", UserPrefs)
    if result.action == "accept":
        format_data(data, result.data.format)
    ```

    **Resource access**: Read MCP resources during tool execution:

    ```python
    content = await ctx.read_resource("file://data/config.json")
    ```

    **Capability checking**: Verify client support before using advanced features:

    ```python
    if ctx.session.check_client_capability(types.ClientCapabilities(sampling=...)):
        # Use advanced features
        pass
    ```

    ## Examples

    Complete tool with context usage:

    ```python
    from pydantic import BaseModel
    from mcp.server.fastmcp import FastMCP, Context

    class ProcessingOptions(BaseModel):
        format: str
        include_metadata: bool

    mcp = FastMCP(name="processor")

    @mcp.tool()
    async def process_data(
        data: str,
        ctx: Context,
        auto_format: bool = False
    ) -> str:
        await ctx.info(f"Starting to process {len(data)} characters")

        # Get user preferences if not auto-formatting
        if not auto_format:
            if ctx.session.check_client_capability(
                types.ClientCapabilities(elicitation=types.ElicitationCapability())
            ):
                prefs_result = await ctx.elicit(
                    "How would you like the data processed?",
                    ProcessingOptions
                )
                if prefs_result.action == "accept":
                    format_type = prefs_result.data.format
                    include_meta = prefs_result.data.include_metadata
                else:
                    await ctx.warning("Using default format")
                    format_type = "standard"
                    include_meta = False
            else:
                format_type = "standard"
                include_meta = False
        else:
            format_type = "auto"
            include_meta = True

        # Process with progress updates
        for i in range(0, len(data), 100):
            chunk = data[i:i+100]
            await ctx.report_progress(i, len(data), f"Processing chunk {i//100 + 1}")
            # ... process chunk

        await ctx.info(f"Processing complete with format: {format_type}")
        return processed_data
    ```

    Note:
        Context objects are request-scoped and automatically managed by FastMCP.
        Don't store references to them beyond the request lifecycle. Each tool
        invocation gets a fresh Context instance tied to that specific request.
    """

    _request_context: RequestContext[ServerSessionT, LifespanContextT, RequestT] | None
    _fastmcp: FastMCP | None

    def __init__(
        self,
        *,
        request_context: (RequestContext[ServerSessionT, LifespanContextT, RequestT] | None) = None,
        fastmcp: FastMCP | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._request_context = request_context
        self._fastmcp = fastmcp

    @property
    def fastmcp(self) -> FastMCP:
        """Access to the FastMCP server."""
        if self._fastmcp is None:
            raise ValueError("Context is not available outside of a request")
        return self._fastmcp

    @property
    def request_context(
        self,
    ) -> RequestContext[ServerSessionT, LifespanContextT, RequestT]:
        """Access to the underlying RequestContext for low-level operations.

        This property provides direct access to the [`RequestContext`][mcp.shared.context.RequestContext]
        that this Context wraps. Use this when you need low-level access to request
        metadata, lifespan context, or other features not exposed by Context's
        convenience methods.

        Most users should prefer Context's convenience methods like `info()`, `elicit()`,
        etc. rather than accessing the underlying RequestContext directly.

        Returns:
            The underlying [`RequestContext`][mcp.shared.context.RequestContext] containing
            session, metadata, and lifespan context.

        Raises:
            ValueError: If called outside of a request context.

        Example:
            ```python
            @mcp.tool()
            async def advanced_tool(data: str, ctx: Context) -> str:
                # Access lifespan context directly
                db = ctx.request_context.lifespan_context["database"]

                # Access request metadata
                progress_token = ctx.request_context.meta.progressToken if ctx.request_context.meta else None

                return processed_data
            ```
        """
        if self._request_context is None:
            raise ValueError("Context is not available outside of a request")
        return self._request_context

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value e.g. 24
            total: Optional total value e.g. 100
            message: Optional message e.g. Starting render...
        """
        progress_token = self.request_context.meta.progressToken if self.request_context.meta else None

        if progress_token is None:
            return

        await self.request_context.session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
        )

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource by URI.

        Args:
            uri: Resource URI to read

        Returns:
            The resource content as either text or bytes
        """
        assert self._fastmcp is not None, "Context is not available outside of a request"
        return await self._fastmcp.read_resource(uri)

    async def elicit(
        self,
        message: str,
        schema: type[ElicitSchemaModelT],
    ) -> ElicitationResult[ElicitSchemaModelT]:
        """Elicit structured information from the client or user during tool execution.

        This method enables interactive data collection from clients during tool processing.
        The client may display the message to the user and collect a response according to
        the provided Pydantic schema, or if the client is an agent, it may automatically
        generate an appropriate response. This is useful for gathering additional parameters,
        user preferences, or confirmation before proceeding with operations.

        You typically access this method through the [`Context`][mcp.server.fastmcp.Context]
        object injected into your FastMCP tool functions. Always check that the client
        supports elicitation using [`check_client_capability`][mcp.server.session.ServerSession.check_client_capability]
        before calling this method.

        Args:
            message: The prompt or question to present to the user. Should clearly explain
                what information is being requested and why it's needed.
            schema: A Pydantic model class defining the expected response structure.
                According to the MCP specification, only primitive types (str, int, float, bool)
                and simple containers (list, dict) are allowed - no complex nested objects.

        Returns:
            `ElicitationResult` containing:

            - `action`: One of "accept", "decline", or "cancel" indicating user response
            - `data`: The structured response data (only populated if action is "accept")

        Raises:
            RuntimeError: If called before session initialization is complete.
            ValidationError: If the client response doesn't match the provided schema.
            Various exceptions: Depending on client implementation and user interaction.

        Examples:
            Collect user preferences before processing:

            ```python
            from pydantic import BaseModel
            from mcp.server.fastmcp import FastMCP, Context

            class ProcessingOptions(BaseModel):
                format: str
                include_metadata: bool
                max_items: int

            mcp = FastMCP(name="example-server")

            @mcp.tool()
            async def process_data(data: str, ctx: Context) -> str:
                # Check if client supports elicitation
                if not ctx.session.check_client_capability(
                    types.ClientCapabilities(elicitation=types.ElicitationCapability())
                ):
                    # Fall back to default processing
                    return process_with_defaults(data)

                # Ask user for processing preferences
                result = await ctx.elicit(
                    "How would you like me to process this data?",
                    ProcessingOptions
                )

                if result.action == "accept":
                    options = result.data
                    await ctx.info(f"Processing with format: {options.format}")
                    return process_with_options(data, options)
                elif result.action == "decline":
                    return process_with_defaults(data)
                else:  # cancel
                    return "Processing cancelled by user"
            ```

            Confirm before destructive operations:

            ```python
            class ConfirmDelete(BaseModel):
                confirm: bool
                reason: str

            @mcp.tool()
            async def delete_files(pattern: str, ctx: Context) -> str:
                files = find_matching_files(pattern)

                result = await ctx.elicit(
                    f"About to delete {len(files)} files matching '{pattern}'. Continue?",
                    ConfirmDelete
                )

                if result.action == "accept" and result.data.confirm:
                    await ctx.info(f"Deletion confirmed: {result.data.reason}")
                    return delete_files(files)
                else:
                    return "Deletion cancelled"
            ```

            Handle different response types:

            ```python
            class UserChoice(BaseModel):
                option: str  # "auto", "manual", "skip"
                details: str

            @mcp.tool()
            async def configure_system(ctx: Context) -> str:
                result = await ctx.elicit(
                    "How should I configure the system?",
                    UserChoice
                )

                match result.action:
                    case "accept":
                        choice = result.data
                        await ctx.info(f"User selected: {choice.option}")
                        return configure_with_choice(choice)
                    case "decline":
                        await ctx.warning("User declined configuration")
                        return "Configuration skipped by user"
                    case "cancel":
                        await ctx.info("Configuration cancelled")
                        return "Operation cancelled"
            ```

        Note:
            The client determines how to handle elicitation requests. Some clients may
            show interactive forms to users, while others may automatically generate
            responses based on context. Always handle all possible action values
            ("accept", "decline", "cancel") in your code and provide appropriate
            fallbacks for clients that don't support elicitation.
        """

        return await elicit_with_validation(
            session=self.request_context.session, message=message, schema=schema, related_request_id=self.request_id
        )

    async def log(
        self,
        level: Literal["debug", "info", "warning", "error"],
        message: str,
        *,
        logger_name: str | None = None,
    ) -> None:
        """Send a log message to the client.

        Args:
            level: Log level (debug, info, warning, error)
            message: Log message
            logger_name: Optional logger name
        """
        await self.request_context.session.send_log_message(
            level=level,
            data=message,
            logger=logger_name,
            related_request_id=self.request_id,
        )

    @property
    def client_id(self) -> str | None:
        """Get the client ID if available."""
        return getattr(self.request_context.meta, "client_id", None) if self.request_context.meta else None

    @property
    def request_id(self) -> str:
        """Get the unique identifier for the current request.

        This ID uniquely identifies the current client request and is useful for
        logging, tracing, error reporting, and linking related operations. It's
        automatically used by Context's convenience methods when sending notifications
        or responses to ensure they're associated with the correct request.

        Returns:
            str: Unique request identifier that can be used for tracing and logging.

        Example:
            ```python
            @mcp.tool()
            async def traceable_tool(data: str, ctx: Context) -> str:
                # Log with request ID for traceability
                print(f"Processing request {ctx.request_id}")

                # Request ID is automatically included in Context methods
                await ctx.info("Starting processing")  # Links to this request

                return processed_data
            ```
        """
        return str(self.request_context.request_id)

    @property
    def session(self) -> ServerSession:
        """Access to the underlying ServerSession for advanced MCP operations.

        This property provides direct access to the [`ServerSession`][mcp.server.session.ServerSession]
        for advanced operations not covered by Context's convenience methods. Use this
        when you need direct session control, capability checking, or low-level MCP
        protocol operations.

        Most users should prefer Context's convenience methods (`info()`, `elicit()`, etc.)
        which internally use this session with appropriate request linking.

        Returns:
            [`ServerSession`][mcp.server.session.ServerSession]: The session for
            communicating with the client and accessing advanced MCP features.

        Examples:
            Capability checking before using advanced features:

            ```python
            @mcp.tool()
            async def advanced_tool(data: str, ctx: Context) -> str:
                # Check client capabilities
                if ctx.session.check_client_capability(
                    types.ClientCapabilities(sampling=types.SamplingCapability())
                ):
                    # Use LLM sampling
                    response = await ctx.session.create_message(
                        messages=[types.SamplingMessage(...)],
                        max_tokens=100
                    )
                    return response.content.text
                else:
                    return "Client doesn't support LLM sampling"
            ```

            Direct resource notifications:

            ```python
            @mcp.tool()
            async def update_resource(uri: str, ctx: Context) -> str:
                # ... update the resource ...

                # Notify client of resource changes
                await ctx.session.send_resource_updated(AnyUrl(uri))
                return "Resource updated"
            ```
        """
        return self.request_context.session

    # Convenience methods for common log levels
    async def debug(self, message: str, **extra: Any) -> None:
        """Send a debug log message."""
        await self.log("debug", message, **extra)

    async def info(self, message: str, **extra: Any) -> None:
        """Send an info log message."""
        await self.log("info", message, **extra)

    async def warning(self, message: str, **extra: Any) -> None:
        """Send a warning log message."""
        await self.log("warning", message, **extra)

    async def error(self, message: str, **extra: Any) -> None:
        """Send an error log message."""
        await self.log("error", message, **extra)
