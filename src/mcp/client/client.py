"""Unified MCP Client that wraps ClientSession with transport management."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import KW_ONLY, dataclass, field
from typing import Any

from mcp.client._memory import InMemoryTransport
from mcp.client._transport import Transport
from mcp.client.session import (
    ClientSession,
    ElicitationFnT,
    ListRootsFnT,
    LoggingFnT,
    MessageHandlerFnT,
    PromptListChangedFnT,
    ResourceListChangedFnT,
    SamplingFnT,
    ToolListChangedFnT,
)
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.shared.session import ProgressFnT
from mcp.types import (
    CallToolResult,
    CompleteResult,
    EmptyResult,
    GetPromptResult,
    Implementation,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    LoggingLevel,
    PaginatedRequestParams,
    PromptReference,
    ReadResourceResult,
    RequestParamsMeta,
    ResourceTemplateReference,
    ServerCapabilities,
)


@dataclass
class Client:
    """A high-level MCP client for connecting to MCP servers.

    Supports in-memory transport for testing (pass a Server or MCPServer instance),
    Streamable HTTP transport (pass a URL string), or a custom Transport instance.

    Example:
        ```python
        from mcp.client import Client
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            return a + b

        async def main():
            async with Client(server) as client:
                result = await client.call_tool("add", {"a": 1, "b": 2})

        asyncio.run(main())
        ```
    """

    server: Server[Any] | MCPServer | Transport | str
    """The MCP server to connect to.

    If the server is a `Server` or `MCPServer` instance, it will be wrapped in an `InMemoryTransport`.
    If the server is a URL string, it will be used as the URL for a `streamable_http_client` transport.
    If the server is a `Transport` instance, it will be used directly.
    """

    _: KW_ONLY

    # TODO(Marcelo): When do `raise_exceptions=True` actually raises?
    raise_exceptions: bool = False
    """Whether to raise exceptions from the server."""

    read_timeout_seconds: float | None = None
    """Timeout for read operations."""

    sampling_callback: SamplingFnT | None = None
    """Callback for handling sampling requests."""

    list_roots_callback: ListRootsFnT | None = None
    """Callback for handling list roots requests."""

    logging_callback: LoggingFnT | None = None
    """Callback for handling logging notifications."""

    # TODO(Marcelo): Why do we have both "callback" and "handler"?
    message_handler: MessageHandlerFnT | None = None
    """Callback for handling raw messages."""

    client_info: Implementation | None = None
    """Client implementation info to send to server."""

    elicitation_callback: ElicitationFnT | None = None
    """Callback for handling elicitation requests."""

    tool_list_changed_callback: ToolListChangedFnT | None = None
    """Callback invoked when the server sends a tools/list_changed notification."""

    resource_list_changed_callback: ResourceListChangedFnT | None = None
    """Callback invoked when the server sends a resources/list_changed notification."""

    prompt_list_changed_callback: PromptListChangedFnT | None = None
    """Callback invoked when the server sends a prompts/list_changed notification."""

    _session: ClientSession | None = field(init=False, default=None)
    _exit_stack: AsyncExitStack | None = field(init=False, default=None)
    _transport: Transport = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.server, Server | MCPServer):
            self._transport = InMemoryTransport(self.server, raise_exceptions=self.raise_exceptions)
        elif isinstance(self.server, str):
            self._transport = streamable_http_client(self.server)
        else:
            self._transport = self.server

    async def __aenter__(self) -> Client:
        """Enter the async context manager."""
        if self._session is not None:
            raise RuntimeError("Client is already entered; cannot reenter")

        async with AsyncExitStack() as exit_stack:
            read_stream, write_stream = await exit_stack.enter_async_context(self._transport)

            self._session = await exit_stack.enter_async_context(
                ClientSession(
                    read_stream=read_stream,
                    write_stream=write_stream,
                    read_timeout_seconds=self.read_timeout_seconds,
                    sampling_callback=self.sampling_callback,
                    list_roots_callback=self.list_roots_callback,
                    logging_callback=self.logging_callback,
                    message_handler=self.message_handler,
                    client_info=self.client_info,
                    elicitation_callback=self.elicitation_callback,
                    tool_list_changed_callback=self.tool_list_changed_callback,
                    resource_list_changed_callback=self.resource_list_changed_callback,
                    prompt_list_changed_callback=self.prompt_list_changed_callback,
                )
            )

            await self._session.initialize()

            # Transfer ownership to self for __aexit__ to handle
            self._exit_stack = exit_stack.pop_all()
            return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """Exit the async context manager."""
        if self._exit_stack:  # pragma: no branch
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
        self._session = None

    @property
    def session(self) -> ClientSession:
        """Get the underlying ClientSession.

        This provides access to the full ClientSession API for advanced use cases.

        Raises:
            RuntimeError: If accessed before entering the context manager.
        """
        if self._session is None:
            raise RuntimeError("Client must be used within an async context manager")
        return self._session

    @property
    def server_capabilities(self) -> ServerCapabilities | None:
        """The server capabilities received during initialization, or None if not yet initialized."""
        return self.session.get_server_capabilities()

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Send a ping request to the server."""
        return await self.session.send_ping(meta=meta)

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Send a progress notification to the server."""
        await self.session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
        )

    async def set_logging_level(self, level: LoggingLevel, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Set the logging level on the server."""
        return await self.session.set_logging_level(level=level, meta=meta)

    async def list_resources(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> ListResourcesResult:
        """List available resources from the server."""
        return await self.session.list_resources(params=PaginatedRequestParams(cursor=cursor, _meta=meta))

    async def list_resource_templates(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> ListResourceTemplatesResult:
        """List available resource templates from the server."""
        return await self.session.list_resource_templates(params=PaginatedRequestParams(cursor=cursor, _meta=meta))

    async def read_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> ReadResourceResult:
        """Read a resource from the server.

        Args:
            uri: The URI of the resource to read.
            meta: Additional metadata for the request.

        Returns:
            The resource content.
        """
        return await self.session.read_resource(uri, meta=meta)

    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Subscribe to resource updates."""
        return await self.session.subscribe_resource(uri, meta=meta)

    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Unsubscribe from resource updates."""
        return await self.session.unsubscribe_resource(uri, meta=meta)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> CallToolResult:
        """Call a tool on the server.

        Args:
            name: The name of the tool to call
            arguments: Arguments to pass to the tool
            read_timeout_seconds: Timeout for the tool call
            progress_callback: Callback for progress updates
            meta: Additional metadata for the request

        Returns:
            The tool result.
        """
        return await self.session.call_tool(
            name=name,
            arguments=arguments,
            read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
            meta=meta,
        )

    async def list_prompts(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> ListPromptsResult:
        """List available prompts from the server."""
        return await self.session.list_prompts(params=PaginatedRequestParams(cursor=cursor, _meta=meta))

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None, *, meta: RequestParamsMeta | None = None
    ) -> GetPromptResult:
        """Get a prompt from the server.

        Args:
            name: The name of the prompt
            arguments: Arguments to pass to the prompt
            meta: Additional metadata for the request

        Returns:
            The prompt content.
        """
        return await self.session.get_prompt(name=name, arguments=arguments, meta=meta)

    async def complete(
        self,
        ref: ResourceTemplateReference | PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> CompleteResult:
        """Get completions for a prompt or resource template argument.

        Args:
            ref: Reference to the prompt or resource template
            argument: The argument to complete
            context_arguments: Additional context arguments

        Returns:
            Completion suggestions.
        """
        return await self.session.complete(ref=ref, argument=argument, context_arguments=context_arguments)

    async def list_tools(self, *, cursor: str | None = None, meta: RequestParamsMeta | None = None) -> ListToolsResult:
        """List available tools from the server."""
        return await self.session.list_tools(params=PaginatedRequestParams(cursor=cursor, _meta=meta))

    async def send_roots_list_changed(self) -> None:
        """Send a notification that the roots list has changed."""
        # TODO(Marcelo): Currently, there is no way for the server to handle this. We should add support.
        await self.session.send_roots_list_changed()  # pragma: no cover
