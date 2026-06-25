"""Unified MCP Client that wraps ClientSession with transport management."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal, TypeVar

import anyio
import mcp_types as types
from mcp_types import (
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
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
from typing_extensions import deprecated

from mcp.client._memory import InMemoryTransport
from mcp.client._probe import negotiate_auto
from mcp.client._transport import Transport
from mcp.client.session import ClientSession, ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.runner import modern_on_request
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import Dispatcher, ProgressFnT
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher

ConnectMode = Literal["legacy", "auto"] | str
"""``mode=`` value: ``"legacy"`` (initialize handshake), ``"auto"`` (discover, fall back to
initialize), or a modern protocol-version string (adopt directly). The ``str`` arm is for
forward-compat; ``Client.__post_init__`` rejects anything outside that set at construction."""

_T = TypeVar("_T")

_Connector = Callable[[AsyncExitStack, ConnectMode, bool], Awaitable["Dispatcher[Any]"]]
"""Resolved at ``__post_init__`` from the shape of ``server`` alone: enter whatever resources
are needed onto the exit stack and hand back the ``Dispatcher`` ``ClientSession`` will drive.
``mode`` and ``raise_exceptions`` are passed at call time so they're read at the same moment
``__aenter__`` reads them for the handshake step."""


def _connect_transport(transport: Transport) -> _Connector:
    """Connector for the stream-backed paths (URL, user-supplied ``Transport``)."""

    async def connect(exit_stack: AsyncExitStack, _mode: ConnectMode, _raise_exceptions: bool) -> Dispatcher[Any]:
        read_stream, write_stream = await exit_stack.enter_async_context(transport)
        return JSONRPCDispatcher(read_stream, write_stream)

    return connect


def _connect_inproc(server: Server[Any]) -> _Connector:
    """Connector for an in-process ``Server``: legacy mode drives the stream loop via
    ``InMemoryTransport``; any other mode drives the modern per-request path through a
    ``DirectDispatcher`` peer pair (no streams, no JSON-RPC framing, no initialize handshake)."""

    async def connect(exit_stack: AsyncExitStack, mode: ConnectMode, raise_exceptions: bool) -> Dispatcher[Any]:
        if mode == "legacy":
            transport = InMemoryTransport(server, raise_exceptions=raise_exceptions)
            read_stream, write_stream = await exit_stack.enter_async_context(transport)
            return JSONRPCDispatcher(read_stream, write_stream)
        lifespan_state = await exit_stack.enter_async_context(server.lifespan(server))
        client_disp, server_disp = create_direct_dispatcher_pair(raise_handler_exceptions=raise_exceptions)
        tg = await exit_stack.enter_async_context(anyio.create_task_group())
        exit_stack.callback(server_disp.close)
        on_request = modern_on_request(server, lifespan_state)
        await tg.start(server_disp.run, on_request, _no_inbound_client_notifications)
        return client_disp

    return connect


def _connected(value: _T | None) -> _T:
    """Narrow a post-handshake session attribute from ``T | None`` to ``T``.

    ``Client.__aenter__`` only assigns ``_session`` after the handshake succeeds, so inside
    ``async with Client(...)`` these attributes are always populated; the ``.session`` gate
    raises before this is reached otherwise. The guard exists for pyright, not runtime.
    """
    if value is None:  # pragma: no cover
        raise RuntimeError("Client must be used within an async context manager")
    return value


def _synthesize_discover(protocol_version: str) -> types.DiscoverResult:
    return types.DiscoverResult(
        supported_versions=[protocol_version],
        capabilities=types.ServerCapabilities(),
        server_info=types.Implementation(name="", version=""),
        result_type="complete",
        ttl_ms=0,
        cache_scope="public",
    )


async def _no_inbound_client_notifications(_dctx: Any, _method: str, _params: Mapping[str, Any] | None) -> None:
    """Server-side inbound ``OnNotify`` for the modern in-process path — receives nothing.

    At 2026-07-28 the spec defines no client→server notifications: ``initialized`` and
    ``roots/list_changed`` are removed, and cancellation is structural (anyio scope cancel
    through the direct await, not a notify). Server→client notifications (progress, log
    messages) flow the other way via the per-request ``DispatchContext`` into the client's
    callbacks, and are not seen here.
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

    If the server is a `Server` or `MCPServer` instance, it will be connected in-process.
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

    mode: ConnectMode = "auto"
    """How to negotiate the protocol version.

    'auto' (the default) probes `server/discover` and falls back to the initialize handshake on legacy servers;
    for an in-process `Server`/`MCPServer` it dispatches directly without JSON-RPC framing. 'legacy' forces the
    initialize handshake (byte-identical pre-2026 behavior). A modern protocol-version string (e.g. '2026-07-28')
    adopts that version directly without a probe — supply `prior_discover` to reuse a known DiscoverResult, or
    omit it to synthesize a minimal one."""

    prior_discover: types.DiscoverResult | None = None
    """A previously-obtained DiscoverResult to install via .adopt() when mode is a version pin.
    Ignored when mode='legacy'."""

    elicitation_callback: ElicitationFnT | None = None
    """Callback for handling elicitation requests."""

    _entered: bool = field(init=False, default=False)
    _session: ClientSession | None = field(init=False, default=None)
    _exit_stack: AsyncExitStack | None = field(init=False, default=None)
    _connect: _Connector = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.mode not in ("legacy", "auto") and self.mode not in MODERN_PROTOCOL_VERSIONS:
            hint = (
                f" ({self.mode!r} is a handshake-era version — use mode='legacy')"
                if self.mode in HANDSHAKE_PROTOCOL_VERSIONS
                else ""
            )
            raise ValueError(
                f"mode must be 'legacy', 'auto', or one of {list(MODERN_PROTOCOL_VERSIONS)}; got {self.mode!r}{hint}"
            )

        srv = self.server
        if isinstance(srv, MCPServer):
            srv = srv._lowlevel_server  # pyright: ignore[reportPrivateUsage]
        if isinstance(srv, Server):
            self._connect = _connect_inproc(srv)
        elif isinstance(srv, str):
            self._connect = _connect_transport(streamable_http_client(srv))
        else:
            self._connect = _connect_transport(srv)

    async def _build_session(self, exit_stack: AsyncExitStack) -> ClientSession:
        """Enter the resolved connector and return an un-entered ClientSession."""
        dispatcher = await self._connect(exit_stack, self.mode, self.raise_exceptions)
        return ClientSession(
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
        if self._entered:
            raise RuntimeError("Client is already entered; cannot reenter")
        self._entered = True

        async with AsyncExitStack() as exit_stack:
            session = await self._build_session(exit_stack)
            session = await exit_stack.enter_async_context(session)

            if self.mode == "legacy":
                await session.initialize()
            elif self.mode == "auto":
                await negotiate_auto(session)
            else:
                session.adopt(self.prior_discover or _synthesize_discover(self.mode))

            # Only publish the session after the handshake succeeds, so `_session is not None`
            # implies the protocol_version/server_info/server_capabilities are populated. If the
            # handshake raised above, the local exit_stack unwinds the transport for us.
            self._session = session
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

    # TODO(maxisbey): the by-construction shape is for __aenter__ to return a connected-view
    # type whose protocol_version/server_info/server_capabilities are non-Optional fields,
    # eliminating these guards (and the one in .session). Same family as resolving the
    # transport/connector at __post_init__ so the Optional internal fields disappear.
    @property
    def protocol_version(self) -> str:
        """Negotiated protocol version (set by initialize/discover/adopt during ``__aenter__``)."""
        return _connected(self.session.protocol_version)

    @property
    def server_info(self) -> Implementation:
        """Server name/version (set by initialize/discover/adopt during ``__aenter__``)."""
        return _connected(self.session.server_info)

    @property
    def server_capabilities(self) -> ServerCapabilities:
        """Server capabilities (set by initialize/discover/adopt during ``__aenter__``)."""
        return _connected(self.session.server_capabilities)

    @property
    def instructions(self) -> str | None:
        """Server-provided instructions text, if any."""
        return self.session.instructions

    @deprecated(
        "ping is removed as of 2026-07-28; the method only works under mode='legacy'.",
        category=MCPDeprecationWarning,
    )
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
