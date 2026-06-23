"""Unified MCP Client that wraps ClientSession with transport management."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal

import anyio
from typing_extensions import deprecated

from mcp import types
from mcp.client._memory import InMemoryTransport
from mcp.client._transport import Transport
from mcp.client.session import ClientSession, ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.runner import modern_on_request
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import Dispatcher, ProgressFnT
from mcp.shared.exceptions import MCPDeprecationWarning, MCPError
from mcp.shared.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
from mcp.types import (
    METHOD_NOT_FOUND,
    REQUEST_TIMEOUT,
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

ConnectMode = Literal["legacy", "auto"] | str
"""``mode=`` value: ``"legacy"`` (initialize handshake), ``"auto"`` (discover, fall back to
initialize), or a modern protocol-version string (adopt directly). The ``str`` arm is for
forward-compat; ``Client.__post_init__`` rejects anything outside that set at construction."""


def _synthesize_discover(protocol_version: str) -> types.DiscoverResult:
    return types.DiscoverResult(
        supported_versions=[protocol_version],
        capabilities=types.ServerCapabilities(),
        server_info=types.Implementation(name="", version=""),
        result_type="complete",
        ttl_ms=0,
        cache_scope="public",
    )


async def _drop_notify(_dctx: Any, _method: str, _params: Mapping[str, Any] | None) -> None:
    """Server-side ``OnNotify`` for the modern in-process path: client→server notifications are dropped.

    The per-request driver (`serve_one`) has no notification dispatch table; progress and
    cancellation travel via `CallOptions` on the `DirectDispatcher`, not as JSON-RPC notifies.
    """


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

    mode: ConnectMode = "legacy"
    """'legacy' performs the initialize handshake. 'auto' probes server/discover and falls back to initialize()
    on legacy servers. A modern protocol-version string (e.g. '2026-07-28') adopts that version directly without
    a handshake — supply prior_discover to reuse a known DiscoverResult, or omit it to synthesize a minimal one."""

    prior_discover: types.DiscoverResult | None = None
    """A previously-obtained DiscoverResult to install via .adopt() when mode is a version pin.
    Ignored when mode='legacy'."""

    elicitation_callback: ElicitationFnT | None = None
    """Callback for handling elicitation requests."""

    _session: ClientSession | None = field(init=False, default=None)
    _exit_stack: AsyncExitStack | None = field(init=False, default=None)
    _transport: Transport | None = field(init=False, default=None)
    _inproc_server: Server[Any] | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if isinstance(self.server, MCPServer):
            self._inproc_server = self.server._lowlevel_server  # pyright: ignore[reportPrivateUsage]
        elif isinstance(self.server, Server):
            self._inproc_server = self.server
        elif isinstance(self.server, str):
            self._transport = streamable_http_client(self.server)
        else:
            self._transport = self.server

        if self.mode not in ("legacy", "auto") and self.mode not in MODERN_PROTOCOL_VERSIONS:
            hint = (
                f" ({self.mode!r} is a handshake-era version — use mode='legacy')"
                if self.mode in HANDSHAKE_PROTOCOL_VERSIONS
                else ""
            )
            raise ValueError(
                f"mode must be 'legacy', 'auto', or one of {list(MODERN_PROTOCOL_VERSIONS)}; got {self.mode!r}{hint}"
            )

    async def _build_session(self, exit_stack: AsyncExitStack) -> ClientSession:
        """Set up the dispatcher/transport and return an un-entered ClientSession."""
        dispatcher: Dispatcher[Any] | None
        if self._inproc_server is not None and self.mode != "legacy":
            # Modern in-process path: drive the server through a DirectDispatcher peer-pair
            # with one `serve_one` per request — no streams, no initialize handshake.
            lifespan_state = await exit_stack.enter_async_context(self._inproc_server.lifespan(self._inproc_server))
            client_disp, server_disp = create_direct_dispatcher_pair()
            tg = await exit_stack.enter_async_context(anyio.create_task_group())
            exit_stack.callback(server_disp.close)
            on_request = modern_on_request(self._inproc_server, lifespan_state, raise_exceptions=self.raise_exceptions)
            await tg.start(server_disp.run, on_request, _drop_notify)
            dispatcher = client_disp
            read_stream = write_stream = None
        else:
            if self._inproc_server is not None:
                transport: Transport = InMemoryTransport(self._inproc_server, raise_exceptions=self.raise_exceptions)
            else:
                assert self._transport is not None
                transport = self._transport
            read_stream, write_stream = await exit_stack.enter_async_context(transport)
            dispatcher = None
        return ClientSession(
            read_stream=read_stream,
            write_stream=write_stream,
            dispatcher=dispatcher,
            read_timeout_seconds=self.read_timeout_seconds,
            sampling_callback=self.sampling_callback,
            list_roots_callback=self.list_roots_callback,
            logging_callback=self.logging_callback,
            message_handler=self.message_handler,
            client_info=self.client_info,
            elicitation_callback=self.elicitation_callback,
        )

    async def __aenter__(self) -> Client:
        """Enter the async context manager."""
        if self._session is not None:
            raise RuntimeError("Client is already entered; cannot reenter")

        async with AsyncExitStack() as exit_stack:
            session = await self._build_session(exit_stack)
            self._session = await exit_stack.enter_async_context(session)

            if self.mode == "legacy":
                await self._session.initialize()
            elif self.mode == "auto":
                try:
                    await self._session.discover()
                except MCPError as e:
                    if e.code in (METHOD_NOT_FOUND, REQUEST_TIMEOUT):
                        await self._session.initialize()
                    else:
                        raise
            else:
                self._session.adopt(self.prior_discover or _synthesize_discover(self.mode))

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
    def protocol_version(self) -> str:
        """Negotiated protocol version (set by initialize/discover/adopt during ``__aenter__``)."""
        version = self.session.protocol_version
        assert version is not None
        return version

    @property
    def server_info(self) -> Implementation:
        """Server name/version (set by initialize/discover/adopt during ``__aenter__``)."""
        info = self.session.server_info
        assert info is not None
        return info

    @property
    def server_capabilities(self) -> ServerCapabilities:
        """Server capabilities (set by initialize/discover/adopt during ``__aenter__``)."""
        caps = self.session.server_capabilities
        assert caps is not None
        return caps

    @property
    def instructions(self) -> str | None:
        """Server-provided instructions text, if any."""
        return self.session.instructions

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Send a ping request to the server."""
        return await self.session.send_ping(meta=meta)

    @deprecated(
        "Client-to-server progress is deprecated as of 2026-07-28; progress is server-to-client only.",
        category=MCPDeprecationWarning,
    )
    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Send a progress notification to the server."""
        await self.session.send_progress_notification(  # pyright: ignore[reportDeprecated]
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
        )

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def set_logging_level(self, level: LoggingLevel, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Set the logging level on the server."""
        return await self.session.set_logging_level(level=level, meta=meta)  # pyright: ignore[reportDeprecated]

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

    @deprecated("The roots capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def send_roots_list_changed(self) -> None:
        """Send a notification that the roots list has changed."""
        # TODO(Marcelo): Currently, there is no way for the server to handle this. We should add support.
        await self.session.send_roots_list_changed()  # pyright: ignore[reportDeprecated]
