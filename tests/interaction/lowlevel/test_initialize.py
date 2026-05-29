"""Initialization handshake against the low-level Server.

The first two tests drive a bare ClientSession by hand because v1's `connect` fixture discards the
`initialize()` return value and `ClientSession` does not cache it; capturing `serverInfo` and
`instructions` therefore requires owning the `initialize()` call. The later tests drive a bare
ClientSession over hand-built memory streams for a different reason: the connected session always
performs the full handshake with the latest protocol version, so skipping initialization or
requesting a different version can only be expressed one level down. The final tests go one step
further and play the server's side of the wire by hand, because no real Server can be made to
answer initialize with an unsupported protocol version.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import AnyUrl

from mcp import McpError, types
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.shared.context import RequestContext
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    INVALID_PARAMS,
    CallToolResult,
    ClientCapabilities,
    ClientRequest,
    CompletionsCapability,
    EmptyResult,
    ErrorData,
    Icon,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsRequest,
    ListToolsResult,
    LoggingCapability,
    PromptsCapability,
    ResourcesCapability,
    ServerCapabilities,
    TextContent,
    ToolsCapability,
)
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


async def _initialize(server: Server[Any]) -> InitializeResult:
    """Connect a bare ClientSession to `server` over in-memory streams and return its initialize result.

    v1's `ClientSession` does not cache the initialize result and the `connect` fixture discards it,
    so tests that need `serverInfo` or `instructions` own the `initialize()` call themselves.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: server.run(server_read, server_write, server.create_initialization_options()))
            async with ClientSession(client_read, client_write) as session:
                with anyio.fail_after(5):
                    initialize_result = await session.initialize()
            tg.cancel_scope.cancel()  # pragma: lax no cover  — python/cpython#106749 (3.11 tracer dead-zone)
    return initialize_result


@asynccontextmanager
async def _bare_session(server: Server[Any]) -> AsyncIterator[ClientSession]:
    """Yield an *uninitialized* ClientSession connected to `server` over in-memory streams.

    Unlike the `connect` fixture this does not call `initialize()`, so tests can drive the
    handshake (or skip it) themselves. This is the v1 spelling of v2's `InMemoryTransport(server)`.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(lambda: server.run(server_read, server_write, server.create_initialization_options()))
            async with ClientSession(client_read, client_write) as session:
                yield session
            tg.cancel_scope.cancel()  # pragma: lax no cover  — python/cpython#106749 (3.11 tracer dead-zone)


@requirement("lifecycle:initialize:basic")
@requirement("lifecycle:initialize:server-info")
async def test_initialize_returns_server_info() -> None:
    """Every identity field the server declares is returned to the client in serverInfo.

    v1's low-level `Server` accepts `name`, `version`, `website_url`, and `icons`; it has no
    `title` or `description` arguments, so those fields are absent from the result.
    """
    server = Server(
        "greeter",
        version="1.2.3",
        website_url="https://example.com/greeter",
        icons=[Icon(src="https://example.com/icon.png", mimeType="image/png", sizes=["48x48"])],
    )

    initialize_result = await _initialize(server)

    assert initialize_result.serverInfo == snapshot(
        Implementation(
            name="greeter",
            version="1.2.3",
            websiteUrl="https://example.com/greeter",
            icons=[Icon(src="https://example.com/icon.png", mimeType="image/png", sizes=["48x48"])],
        )
    )


@requirement("lifecycle:initialize:instructions")
async def test_initialize_returns_instructions() -> None:
    """Instructions are returned when the server declares them and omitted when it does not."""
    initialize_result = await _initialize(Server("guided", instructions="Call the add tool."))
    assert initialize_result.instructions == snapshot("Call the add tool.")

    initialize_result = await _initialize(Server("unguided"))
    assert initialize_result.instructions is None


@requirement("lifecycle:initialize:capabilities:from-handlers")
@requirement("tools:capability:declared")
@requirement("resources:capability:declared")
@requirement("prompts:capability:declared")
@requirement("completion:capability:declared")
async def test_initialize_capabilities_reflect_registered_handlers(connect: Connect) -> None:
    """Each feature area with a registered handler is advertised as a capability.

    The `connect` fixture uses default initialization options, so the listChanged flags are always
    False regardless of the server's notification behaviour. v1 also hard-codes `subscribe=False`
    even when a `subscribe_resource` handler is registered; the handler is registered here anyway
    to pin that divergence.
    """
    server = Server("full")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        """Registered only so the tools capability is advertised; never called."""
        raise NotImplementedError

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        """Registered only so the resources capability is advertised; never called."""
        raise NotImplementedError

    @server.subscribe_resource()
    async def subscribe_resource(uri: AnyUrl) -> None:
        """Registered to show v1 still advertises subscribe=False; never called."""
        raise NotImplementedError

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        """Registered only so the prompts capability is advertised; never called."""
        raise NotImplementedError

    @server.set_logging_level()
    async def set_logging_level(level: types.LoggingLevel) -> None:
        """Registered only so the logging capability is advertised; never called."""
        raise NotImplementedError

    @server.completion()
    async def completion(
        ref: types.PromptReference | types.ResourceTemplateReference,
        argument: types.CompletionArgument,
        context: types.CompletionContext | None,
    ) -> types.Completion | None:
        """Registered only so the completions capability is advertised; never called."""
        raise NotImplementedError

    async with connect(server) as client:
        capabilities = client.get_server_capabilities()

    assert capabilities == snapshot(
        ServerCapabilities(
            experimental={},
            logging=LoggingCapability(),
            prompts=PromptsCapability(listChanged=False),
            resources=ResourcesCapability(subscribe=False, listChanged=False),
            tools=ToolsCapability(listChanged=False),
            completions=CompletionsCapability(),
        )
    )


@requirement("lifecycle:initialize:capabilities:minimal")
async def test_initialize_minimal_server_advertises_no_capabilities(connect: Connect) -> None:
    """A server with no feature handlers advertises no feature capabilities."""
    async with connect(Server("bare")) as client:
        capabilities = client.get_server_capabilities()

    assert capabilities == snapshot(ServerCapabilities(experimental={}))


@requirement("lifecycle:initialize:client-info")
async def test_initialize_server_sees_client_info(connect: Connect) -> None:
    """The client identity supplied to ClientSession is visible to server handlers after initialization."""
    server = Server("introspector")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="whoami", description="Report the caller.", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "whoami"
        client_params = server.request_context.session.client_params
        assert client_params is not None
        client_info = client_params.clientInfo
        return [TextContent(type="text", text=f"{client_info.name} {client_info.version}")]

    async with connect(server, client_info=Implementation(name="acme-agent", version="9.9.9")) as client:
        result = await client.call_tool("whoami", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="acme-agent 9.9.9")]))


@requirement("lifecycle:initialize:client-capabilities")
async def test_initialize_server_sees_client_capabilities(connect: Connect) -> None:
    """The client capabilities visible to the server reflect which callbacks the client configured."""
    server = Server("introspector")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="abilities", description="Report capabilities.", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "abilities"
        client_params = server.request_context.session.client_params
        assert client_params is not None
        capabilities = client_params.capabilities
        declared = [
            label
            for label, value in (
                ("sampling", capabilities.sampling),
                ("elicitation", capabilities.elicitation),
            )
            if value is not None
        ]
        if capabilities.roots is not None:
            declared.append(f"roots(list_changed={capabilities.roots.listChanged})")
        return [TextContent(type="text", text=",".join(declared) or "none")]

    async def list_roots(context: RequestContext[ClientSession, Any]) -> types.ListRootsResult | types.ErrorData:
        """Registered only so the client declares the roots capability; never called."""
        raise NotImplementedError

    async with connect(server) as client:
        result = await client.call_tool("abilities", {})
    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="none")]))

    async with connect(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("abilities", {})
    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="roots(list_changed=True)")]))


@requirement("lifecycle:requests-before-initialized")
async def test_request_before_initialization_is_rejected() -> None:
    """A feature request sent before the handshake completes is rejected; ping is exempt.

    The `connect` fixture always initializes on entry, so this drives a bare ClientSession that
    never sends initialize. The server's stated reason for the rejection never reaches the client:
    the error is reported as a generic invalid-params failure.
    """
    server = Server("strict")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        """Registered so the request is routed to a real handler; never reached."""
        raise NotImplementedError

    async with _bare_session(server) as session:
        with anyio.fail_after(5):
            with pytest.raises(McpError) as exc_info:
                await session.send_request(ClientRequest(ListToolsRequest()), ListToolsResult)

            # Ping is explicitly permitted before initialization completes.
            pong = await session.send_ping()

    assert exc_info.value.error == snapshot(
        ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
    )
    assert pong == snapshot(EmptyResult())


@requirement("lifecycle:version:match")
@requirement("lifecycle:version:server-fallback-latest")
async def test_initialize_negotiates_protocol_version() -> None:
    """The server echoes a supported requested version and answers an unsupported one with its latest.

    Client always requests the latest version, so each half hand-builds an InitializeRequest on a
    bare ClientSession to control the requested version.
    """
    server = Server("negotiator")

    def initialize_request(protocol_version: str) -> ClientRequest:
        return ClientRequest(
            InitializeRequest(
                params=InitializeRequestParams(
                    protocolVersion=protocol_version,
                    capabilities=ClientCapabilities(),
                    clientInfo=Implementation(name="time-traveller", version="0.0.1"),
                )
            )
        )

    async with _bare_session(server) as session:
        with anyio.fail_after(5):
            result = await session.send_request(initialize_request("2025-03-26"), InitializeResult)
    assert result.protocolVersion == snapshot("2025-03-26")

    async with _bare_session(server) as session:
        with anyio.fail_after(5):
            result = await session.send_request(initialize_request("1999-01-01"), InitializeResult)
    assert result.protocolVersion == snapshot("2025-11-25")


@requirement("lifecycle:version:reject-unsupported")
async def test_unsupported_server_protocol_version_fails_initialization() -> None:
    """An initialize response carrying a protocol version the client does not support fails initialization.

    A real Server only ever answers with a version it supports, so this test alone plays the
    server's side of the wire by hand: it reads the initialize request off the raw stream and
    answers it with a hand-built result. Reserve this pattern for behaviour no real server can
    be made to produce.
    """

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        message = await server_read.receive()
        assert isinstance(message, SessionMessage)
        request = message.message.root
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "initialize"
        result = InitializeResult(
            protocolVersion="1991-08-06",
            capabilities=ServerCapabilities(),
            serverInfo=Implementation(name="relic", version="0.0.1"),
        )
        await server_write.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=request.id,
                        # Serialized exactly as a real server serializes results onto the wire.
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as tg,
        ClientSession(client_read, client_write) as session,
    ):
        tg.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            with pytest.raises(RuntimeError) as exc_info:
                await session.initialize()

        assert str(exc_info.value) == snapshot("Unsupported protocol version from the server: 1991-08-06")


@requirement("lifecycle:version:downgrade")
async def test_an_older_supported_protocol_version_from_the_server_is_accepted() -> None:
    """An initialize response carrying an older supported protocol version completes the handshake at that version.

    A real Server answers with the version the client requested (or its own latest), so this test
    plays the server's side of the wire by hand to return a fixed older version regardless of what
    was requested. Reserve this pattern for behaviour no real server can be made to produce.
    """

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        message = await server_read.receive()
        assert isinstance(message, SessionMessage)
        request = message.message.root
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "initialize"
        result = InitializeResult(
            protocolVersion="2025-06-18",
            capabilities=ServerCapabilities(),
            serverInfo=Implementation(name="conservative", version="0.0.1"),
        )
        await server_write.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=request.id,
                        # Serialized exactly as a real server serializes results onto the wire.
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as tg,
        ClientSession(client_read, client_write) as session,
    ):
        tg.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            initialize_result = await session.initialize()

        assert initialize_result.protocolVersion == snapshot("2025-06-18")
