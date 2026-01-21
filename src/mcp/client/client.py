"""Unified MCP Client that wraps ClientSession with transport management."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import mcp.types as types
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession, ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.shared.session import ProgressFnT
from mcp.types._types import RequestParamsMeta


class Client:
    """A high-level MCP client for connecting to MCP servers.

    Currently supports in-memory transport for testing. Pass a Server or
    FastMCP instance directly to the constructor.

    Example:
        ```python
        from mcp.client import Client
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            return a + b

        async def main():
            async with Client(server) as client:
                result = await client.call_tool("add", {"a": 1, "b": 2})

        asyncio.run(main())
        ```
    """

    # TODO(felixweinberger): Expand to support all transport types (like FastMCP 2):
    # - Add ClientTransport base class with connect_session() method
    # - Add StreamableHttpTransport, SSETransport, StdioTransport
    # - Add infer_transport() to auto-detect transport from input type
    # - Accept URL strings, Path objects, config dicts in constructor
    # - Add auth support (OAuth, bearer tokens)

    def __init__(
        self,
        server: Server[Any] | FastMCP,
        *,
        # TODO(Marcelo): When do `raise_exceptions=True` actually raises?
        raise_exceptions: bool = False,
        read_timeout_seconds: float | None = None,
        sampling_callback: SamplingFnT | None = None,
        list_roots_callback: ListRootsFnT | None = None,
        logging_callback: LoggingFnT | None = None,
        message_handler: MessageHandlerFnT | None = None,
        client_info: types.Implementation | None = None,
        elicitation_callback: ElicitationFnT | None = None,
    ) -> None:
        """Initialize the client with a server.

        Args:
            server: The MCP server to connect to (Server or FastMCP instance)
            raise_exceptions: Whether to raise exceptions from the server
            read_timeout_seconds: Timeout for read operations
            sampling_callback: Callback for handling sampling requests
            list_roots_callback: Callback for handling list roots requests
            logging_callback: Callback for handling logging notifications
            message_handler: Callback for handling raw messages
            client_info: Client implementation info to send to server
            elicitation_callback: Callback for handling elicitation requests
        """
        self._server = server
        self._raise_exceptions = raise_exceptions
        self._read_timeout_seconds = read_timeout_seconds
        self._sampling_callback = sampling_callback
        self._list_roots_callback = list_roots_callback
        self._logging_callback = logging_callback
        self._message_handler = message_handler
        self._client_info = client_info
        self._elicitation_callback = elicitation_callback

        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def __aenter__(self) -> Client:
        """Enter the async context manager."""
        if self._session is not None:
            raise RuntimeError("Client is already entered; cannot reenter")

        async with AsyncExitStack() as exit_stack:
            # Create transport and connect
            transport = InMemoryTransport(self._server, raise_exceptions=self._raise_exceptions)
            read_stream, write_stream = await exit_stack.enter_async_context(transport.connect())

            # Create session
            self._session = await exit_stack.enter_async_context(
                ClientSession(
                    read_stream=read_stream,
                    write_stream=write_stream,
                    read_timeout_seconds=self._read_timeout_seconds,
                    sampling_callback=self._sampling_callback,
                    list_roots_callback=self._list_roots_callback,
                    logging_callback=self._logging_callback,
                    message_handler=self._message_handler,
                    client_info=self._client_info,
                    elicitation_callback=self._elicitation_callback,
                )
            )

            # Initialize the session
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
    def server_capabilities(self) -> types.ServerCapabilities | None:
        """The server capabilities received during initialization, or None if not yet initialized."""
        return self.session.get_server_capabilities()

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
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

    async def set_logging_level(
        self,
        level: types.LoggingLevel,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.EmptyResult:
        """Set the logging level on the server."""
        return await self.session.set_logging_level(level=level, meta=meta)

    async def list_resources(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> types.ListResourcesResult:
        """List available resources from the server."""
        return await self.session.list_resources(params=types.PaginatedRequestParams(cursor=cursor, _meta=meta))

    async def list_resource_templates(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> types.ListResourceTemplatesResult:
        """List available resource templates from the server."""
        return await self.session.list_resource_templates(
            params=types.PaginatedRequestParams(cursor=cursor, _meta=meta)
        )

    async def read_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.ReadResourceResult:
        """Read a resource from the server.

        Args:
            uri: The URI of the resource to read.

        Returns:
            The resource content.
        """
        return await self.session.read_resource(uri, meta=meta)

    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Subscribe to resource updates."""
        return await self.session.subscribe_resource(uri, meta=meta)

    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
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
    ) -> types.CallToolResult:
        """Call a tool on the server.

        Args:
            name: The name of the tool to call
            arguments: Arguments to pass to the tool
            read_timeout_seconds: Timeout for the tool call
            progress_callback: Callback for progress updates
            meta: Additional metadata for the request

        Returns:
            The tool result
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
    ) -> types.ListPromptsResult:
        """List available prompts from the server."""
        return await self.session.list_prompts(params=types.PaginatedRequestParams(cursor=cursor, _meta=meta))

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> types.GetPromptResult:
        """Get a prompt from the server.

        Args:
            name: The name of the prompt
            arguments: Arguments to pass to the prompt

        Returns:
            The prompt content.
        """
        return await self.session.get_prompt(name=name, arguments=arguments)

    async def complete(
        self,
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> types.CompleteResult:
        """Get completions for a prompt or resource template argument.

        Args:
            ref: Reference to the prompt or resource template
            argument: The argument to complete
            context_arguments: Additional context arguments

        Returns:
            Completion suggestions.
        """
        return await self.session.complete(ref=ref, argument=argument, context_arguments=context_arguments)

    async def list_tools(self, *, cursor: str | None = None) -> types.ListToolsResult:
        """List available tools from the server."""
        return await self.session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))

    async def send_roots_list_changed(self) -> None:
        """Send a notification that the roots list has changed."""
        # TODO(Marcelo): Currently, there is no way for the server to handle this. We should add support.
        await self.session.send_roots_list_changed()  # pragma: no cover
