"""Initialization handshake against the low-level Server, driven through the public Client API.

The later tests drive a bare ClientSession over an InMemoryTransport instead: Client always
performs the full handshake with the latest protocol version, so skipping initialization or
requesting a different version can only be expressed one level down. The final test goes one step
further and plays the server's side of the wire by hand, because no real Server can be made to
answer initialize with an unsupported protocol version.
"""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    CallToolResult,
    ClientCapabilities,
    CompletionsCapability,
    EmptyResult,
    ErrorData,
    Icon,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
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

from mcp import MCPError
from mcp.client import ClientRequestContext, ClientSession
from mcp.client._memory import InMemoryTransport
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lifecycle:initialize:basic")
@requirement("lifecycle:initialize:server-info")
async def test_initialize_returns_server_info(connect: Connect) -> None:
    """Every identity field the server declares is returned to the client in server_info."""
    server = Server(
        "greeter",
        version="1.2.3",
        title="Greeter",
        description="Greets people.",
        website_url="https://example.com/greeter",
        icons=[Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48"])],
    )

    async with connect(server) as client:
        server_info = client.initialize_result.server_info

    assert server_info == snapshot(
        Implementation(
            name="greeter",
            title="Greeter",
            description="Greets people.",
            version="1.2.3",
            website_url="https://example.com/greeter",
            icons=[Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48"])],
        )
    )


@requirement("lifecycle:initialize:instructions")
async def test_initialize_returns_instructions(connect: Connect) -> None:
    """Instructions are returned when the server declares them and omitted when it does not."""
    async with connect(Server("guided", instructions="Call the add tool.")) as client:
        assert client.initialize_result.instructions == snapshot("Call the add tool.")

    async with connect(Server("unguided")) as client:
        assert client.initialize_result.instructions is None


@requirement("lifecycle:initialize:capabilities:from-handlers")
@requirement("tools:capability:declared")
@requirement("resources:capability:declared")
@requirement("prompts:capability:declared")
@requirement("completion:capability:declared")
async def test_initialize_capabilities_reflect_registered_handlers(connect: Connect) -> None:
    """Each feature area with a registered handler is advertised as a capability.

    The in-memory transport connects with default initialization options, so the
    list_changed flags are always False regardless of the server's notification behaviour.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        """Registered only so the tools capability is advertised; never called."""
        raise NotImplementedError

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        """Registered only so the resources capability is advertised; never called."""
        raise NotImplementedError

    async def subscribe_resource(ctx: ServerRequestContext, params: types.SubscribeRequestParams) -> types.EmptyResult:
        """Registered only so the subscribe sub-capability is advertised; never called."""
        raise NotImplementedError

    async def list_prompts(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        """Registered only so the prompts capability is advertised; never called."""
        raise NotImplementedError

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> types.EmptyResult:
        """Registered only so the logging capability is advertised; never called."""
        raise NotImplementedError

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> types.CompleteResult:
        """Registered only so the completions capability is advertised; never called."""
        raise NotImplementedError

    server = Server(
        "full",
        on_list_tools=list_tools,
        on_list_resources=list_resources,
        on_subscribe_resource=subscribe_resource,
        on_list_prompts=list_prompts,
        on_set_logging_level=set_logging_level,
        on_completion=completion,
    )

    async with connect(server) as client:
        capabilities = client.initialize_result.capabilities

    assert capabilities == snapshot(
        ServerCapabilities(
            experimental={},
            logging=LoggingCapability(),
            prompts=PromptsCapability(list_changed=False),
            resources=ResourcesCapability(subscribe=True, list_changed=False),
            tools=ToolsCapability(list_changed=False),
            completions=CompletionsCapability(),
        )
    )


@requirement("lifecycle:initialize:capabilities:minimal")
async def test_initialize_minimal_server_advertises_no_capabilities(connect: Connect) -> None:
    """A server with no feature handlers advertises no feature capabilities."""
    async with connect(Server("bare")) as client:
        capabilities = client.initialize_result.capabilities

    assert capabilities == snapshot(ServerCapabilities(experimental={}))


@requirement("lifecycle:initialize:client-info")
async def test_initialize_server_sees_client_info(connect: Connect) -> None:
    """The client identity supplied to Client is visible to server handlers after initialization."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="whoami", description="Report the caller.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "whoami"
        assert ctx.session.client_params is not None
        client_info = ctx.session.client_params.client_info
        return CallToolResult(content=[TextContent(text=f"{client_info.name} {client_info.version}")])

    server = Server("introspector", on_list_tools=list_tools, on_call_tool=call_tool)
    async with connect(server, client_info=Implementation(name="acme-agent", version="9.9.9")) as client:
        result = await client.call_tool("whoami", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="acme-agent 9.9.9")]))


@requirement("lifecycle:initialize:client-capabilities")
async def test_initialize_server_sees_client_capabilities(connect: Connect) -> None:
    """The client capabilities visible to the server reflect which callbacks the client configured."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="abilities", description="Report capabilities.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "abilities"
        assert ctx.session.client_params is not None
        capabilities = ctx.session.client_params.capabilities
        declared = [
            name
            for name, value in (
                ("sampling", capabilities.sampling),
                ("elicitation", capabilities.elicitation),
            )
            if value is not None
        ]
        if capabilities.roots is not None:
            declared.append(f"roots(list_changed={capabilities.roots.list_changed})")
        return CallToolResult(content=[TextContent(text=",".join(declared) or "none")])

    async def list_roots(context: ClientRequestContext) -> types.ListRootsResult:
        """Registered only so the client declares the roots capability; never called."""
        raise NotImplementedError

    server = Server("introspector", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("abilities", {})
    assert result == snapshot(CallToolResult(content=[TextContent(text="none")]))

    async with connect(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("abilities", {})
    assert result == snapshot(CallToolResult(content=[TextContent(text="roots(list_changed=True)")]))


@requirement("lifecycle:requests-before-initialized")
async def test_request_before_initialization_is_rejected() -> None:
    """A feature request sent before the handshake completes is rejected; ping is exempt.

    Client always initializes on entry, so this drives a bare ClientSession that never sends
    initialize. The server's stated reason for the rejection never reaches the client: the error
    is reported as a generic invalid-params failure.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        """Registered so the request is routed to a real handler; never reached."""
        raise NotImplementedError

    server = Server("strict", on_list_tools=list_tools)

    async with (
        InMemoryTransport(server) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        with anyio.fail_after(5):
            with pytest.raises(MCPError) as exc_info:
                await session.send_request(ListToolsRequest(), ListToolsResult)

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

    def initialize_request(protocol_version: str) -> InitializeRequest:
        return InitializeRequest(
            params=InitializeRequestParams(
                protocol_version=protocol_version,
                capabilities=ClientCapabilities(),
                client_info=Implementation(name="time-traveller", version="0.0.1"),
            )
        )

    async with (
        InMemoryTransport(server) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        with anyio.fail_after(5):
            result = await session.send_request(initialize_request("2025-03-26"), InitializeResult)
    assert result.protocol_version == snapshot("2025-03-26")

    async with (
        InMemoryTransport(server) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        with anyio.fail_after(5):
            result = await session.send_request(initialize_request("1999-01-01"), InitializeResult)
    assert result.protocol_version == snapshot("2025-11-25")


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
        request = message.message
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "initialize"
        result = InitializeResult(
            protocol_version="1991-08-06",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="relic", version="0.0.1"),
        )
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    # Serialized exactly as a real server serializes results onto the wire.
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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
        request = message.message
        assert isinstance(request, JSONRPCRequest)
        assert request.method == "initialize"
        result = InitializeResult(
            protocol_version="2025-06-18",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="conservative", version="0.0.1"),
        )
        await server_write.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    # Serialized exactly as a real server serializes results onto the wire.
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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

        assert initialize_result.protocol_version == snapshot("2025-06-18")
