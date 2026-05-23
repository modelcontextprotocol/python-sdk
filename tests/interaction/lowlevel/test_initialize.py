"""Initialization handshake against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolResult,
    CompletionsCapability,
    Icon,
    Implementation,
    LoggingCapability,
    PromptsCapability,
    ResourcesCapability,
    ServerCapabilities,
    TextContent,
    ToolsCapability,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lifecycle:initialize:server-info")
async def test_initialize_returns_server_info() -> None:
    """Every identity field the server declares is returned to the client in server_info."""
    server = Server(
        "greeter",
        version="1.2.3",
        title="Greeter",
        description="Greets people.",
        website_url="https://example.com/greeter",
        icons=[Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48"])],
    )

    async with Client(server) as client:
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
async def test_initialize_returns_instructions() -> None:
    """Instructions are returned when the server declares them and omitted when it does not."""
    async with Client(Server("guided", instructions="Call the add tool.")) as client:
        assert client.initialize_result.instructions == snapshot("Call the add tool.")

    async with Client(Server("unguided")) as client:
        assert client.initialize_result.instructions is None


@requirement("lifecycle:initialize:capabilities:from-handlers")
async def test_initialize_capabilities_reflect_registered_handlers() -> None:
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

    async with Client(server) as client:
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
async def test_initialize_minimal_server_advertises_no_capabilities() -> None:
    """A server with no feature handlers advertises no feature capabilities."""
    async with Client(Server("bare")) as client:
        capabilities = client.initialize_result.capabilities

    assert capabilities == snapshot(ServerCapabilities(experimental={}))


@requirement("lifecycle:initialize:client-info")
async def test_initialize_server_sees_client_info() -> None:
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
    client = Client(server, client_info=Implementation(name="acme-agent", version="9.9.9"))

    async with client:
        result = await client.call_tool("whoami", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="acme-agent 9.9.9")]))


@requirement("lifecycle:initialize:client-capabilities")
async def test_initialize_server_sees_client_capabilities() -> None:
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
                ("roots", capabilities.roots),
            )
            if value is not None
        ]
        return CallToolResult(content=[TextContent(text=",".join(declared) or "none")])

    async def list_roots(context: ClientRequestContext) -> types.ListRootsResult:
        """Registered only so the client declares the roots capability; never called."""
        raise NotImplementedError

    server = Server("introspector", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("abilities", {})
    assert result == snapshot(CallToolResult(content=[TextContent(text="none")]))

    async with Client(server, list_roots_callback=list_roots) as client:
        result = await client.call_tool("abilities", {})
    assert result == snapshot(CallToolResult(content=[TextContent(text="roots")]))
