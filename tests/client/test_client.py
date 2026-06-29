"""Tests for the unified Client class."""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import patch

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolResult,
    EmptyResult,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    PromptsCapability,
    ReadResourceResult,
    Resource,
    ResourcesCapability,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
    ToolsCapability,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from pydantic import FileUrl

from mcp import MCPError
from mcp.client._memory import InMemoryTransport
from mcp.client._transport import TransportStreams
from mcp.client.client import Client
from mcp.client.session import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, mounted_app

pytestmark = pytest.mark.anyio


@pytest.fixture
def simple_server() -> Server:
    async def handle_list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(
            resources=[Resource(uri="memory://test", name="Test Resource", description="A test resource")]
        )

    async def handle_subscribe_resource(ctx: ServerRequestContext, params: types.SubscribeRequestParams) -> EmptyResult:
        return EmptyResult()

    async def handle_unsubscribe_resource(
        ctx: ServerRequestContext, params: types.UnsubscribeRequestParams
    ) -> EmptyResult:
        return EmptyResult()

    async def handle_set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        return EmptyResult()

    async def handle_completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> types.CompleteResult:
        return types.CompleteResult(completion=types.Completion(values=[]))

    return Server(  # pyright: ignore[reportDeprecated]
        name="test_server",
        on_list_resources=handle_list_resources,
        on_subscribe_resource=handle_subscribe_resource,
        on_unsubscribe_resource=handle_unsubscribe_resource,
        on_set_logging_level=handle_set_logging_level,
        on_completion=handle_completion,
    )


@pytest.fixture
def app() -> MCPServer:
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"Hello, {name}!"

    @server.resource("test://resource")
    def test_resource() -> str:
        """A test resource."""
        return "Test content"

    @server.prompt()
    def greeting_prompt(name: str) -> str:
        """A greeting prompt."""
        return f"Please greet {name} warmly."

    return server


async def test_client_is_initialized(app: MCPServer):
    async with Client(app, mode="legacy") as client:
        assert client.server_capabilities == snapshot(
            ServerCapabilities(
                experimental={},
                prompts=PromptsCapability(list_changed=False),
                resources=ResourcesCapability(subscribe=False, list_changed=False),
                tools=ToolsCapability(list_changed=False),
            )
        )
        assert client.server_info.name == "test"


async def test_client_exposes_negotiated_protocol_version(app: MCPServer):
    async with Client(app, mode="legacy") as client:
        assert client.protocol_version == LATEST_HANDSHAKE_VERSION


async def test_client_with_simple_server(simple_server: Server):
    async with Client(simple_server) as client:
        resources = await client.list_resources()
        assert resources == snapshot(
            ListResourcesResult(
                resources=[Resource(name="Test Resource", uri="memory://test", description="A test resource")]
            )
        )


async def test_client_send_ping(app: MCPServer):
    async with Client(app, mode="legacy") as client:
        result = await client.send_ping()  # pyright: ignore[reportDeprecated]
        assert result == snapshot(EmptyResult())


async def test_client_list_tools(app: MCPServer):
    async with Client(app) as client:
        result = await client.list_tools()
        assert result == snapshot(
            ListToolsResult(
                tools=[
                    Tool(
                        name="greet",
                        description="Greet someone by name.",
                        input_schema={
                            "properties": {"name": {"title": "Name", "type": "string"}},
                            "required": ["name"],
                            "title": "greetArguments",
                            "type": "object",
                        },
                        output_schema={
                            "properties": {"result": {"title": "Result", "type": "string"}},
                            "required": ["result"],
                            "title": "greetOutput",
                            "type": "object",
                        },
                    )
                ]
            )
        )


async def test_client_call_tool(app: MCPServer):
    async with Client(app) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(text="Hello, World!")],
                structured_content={"result": "Hello, World!"},
            )
        )


async def test_read_resource(app: MCPServer):
    async with Client(app) as client:
        result = await client.read_resource("test://resource")
        assert result == snapshot(
            ReadResourceResult(
                contents=[TextResourceContents(uri="test://resource", mime_type="text/plain", text="Test content")]
            )
        )


async def test_read_resource_error_propagates():
    async def handle_read_resource(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> ReadResourceResult:
        raise MCPError(code=404, message="no resource with that URI was found")

    server = Server("test", on_read_resource=handle_read_resource)
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("unknown://example")
        assert exc_info.value.error.code == 404


async def test_raise_exceptions_propagates_handler_error_on_modern_inproc_path():
    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        raise ValueError("boom")

    server = Server("test", on_call_tool=handle_call_tool)
    async with Client(server, mode="2026-07-28", raise_exceptions=True) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("explode", {})
    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "boom"


async def test_raise_exceptions_false_sanitizes_handler_error_on_modern_inproc_path():
    """Sanitized to opaque `INTERNAL_ERROR` by default so the in-process path matches the wire path's leak guard."""

    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        raise ValueError("boom")

    server = Server("test", on_call_tool=handle_call_tool)
    async with Client(server, mode="2026-07-28", raise_exceptions=False) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("explode", {})
    assert exc_info.value.error.code == types.INTERNAL_ERROR
    assert exc_info.value.error.message == "Internal server error"
    assert exc_info.value.__cause__ is None


async def test_get_prompt(app: MCPServer):
    async with Client(app) as client:
        result = await client.get_prompt("greeting_prompt", {"name": "Alice"})
        assert result == snapshot(
            GetPromptResult(
                description="A greeting prompt.",
                messages=[PromptMessage(role="user", content=TextContent(text="Please greet Alice warmly."))],
            )
        )


def test_client_session_property_before_enter(app: MCPServer):
    client = Client(app)
    with pytest.raises(RuntimeError, match="Client must be used within an async context manager"):
        client.session


async def test_client_reentry_raises_runtime_error(app: MCPServer):
    async with Client(app) as client:
        with pytest.raises(RuntimeError, match="Client is already entered"):
            await client.__aenter__()


async def test_client_send_progress_notification():
    received_from_client = None
    event = anyio.Event()

    async def handle_progress(ctx: ServerRequestContext, params: types.ProgressNotificationParams) -> None:
        nonlocal received_from_client
        received_from_client = {"progress_token": params.progress_token, "progress": params.progress}
        event.set()

    server = Server(name="test_server", on_progress=handle_progress)  # pyright: ignore[reportDeprecated]

    with anyio.fail_after(5):
        async with Client(server, mode="legacy") as client:
            await client.send_progress_notification(progress_token="token123", progress=50.0)  # pyright: ignore[reportDeprecated]
            await event.wait()
            assert received_from_client == snapshot({"progress_token": "token123", "progress": 50.0})


async def test_client_subscribe_resource(simple_server: Server):
    async with Client(simple_server, mode="legacy") as client:
        result = await client.subscribe_resource("memory://test")
        assert result == snapshot(EmptyResult())


async def test_client_unsubscribe_resource(simple_server: Server):
    async with Client(simple_server, mode="legacy") as client:
        result = await client.unsubscribe_resource("memory://test")
        assert result == snapshot(EmptyResult())


async def test_client_set_logging_level(simple_server: Server):
    async with Client(simple_server, mode="legacy") as client:
        result = await client.set_logging_level("debug")  # pyright: ignore[reportDeprecated]
        assert result == snapshot(EmptyResult())


async def test_client_list_resources_with_params(app: MCPServer):
    async with Client(app) as client:
        result = await client.list_resources()
        assert result == snapshot(
            ListResourcesResult(
                resources=[
                    Resource(
                        name="test_resource",
                        uri="test://resource",
                        description="A test resource.",
                        mime_type="text/plain",
                    )
                ]
            )
        )


async def test_client_list_resource_templates(app: MCPServer):
    async with Client(app) as client:
        result = await client.list_resource_templates()
        assert result == snapshot(ListResourceTemplatesResult(resource_templates=[]))


async def test_list_prompts(app: MCPServer):
    async with Client(app) as client:
        result = await client.list_prompts()
        assert result == snapshot(
            ListPromptsResult(
                prompts=[
                    Prompt(
                        name="greeting_prompt",
                        description="A greeting prompt.",
                        arguments=[PromptArgument(name="name", required=True)],
                    )
                ]
            )
        )


async def test_complete_with_prompt_reference(simple_server: Server):
    async with Client(simple_server) as client:
        ref = types.PromptReference(type="ref/prompt", name="test_prompt")
        result = await client.complete(ref=ref, argument={"name": "arg", "value": "test"})
        assert result == snapshot(types.CompleteResult(completion=types.Completion(values=[])))


def test_client_with_url_initializes_streamable_http_transport():
    with patch("mcp.client.client.streamable_http_client") as mock:
        _ = Client("http://localhost:8000/mcp")
    mock.assert_called_once_with("http://localhost:8000/mcp")


async def test_client_uses_transport_directly(app: MCPServer):
    transport = InMemoryTransport(app)
    async with Client(transport, mode="legacy") as client:
        result = await client.call_tool("greet", {"name": "Transport"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(text="Hello, Transport!")],
                structured_content={"result": "Hello, Transport!"},
            )
        )


_TEST_CONTEXTVAR = contextvars.ContextVar("test_var", default="initial")


@contextmanager
def _set_test_contextvar(value: str) -> Iterator[None]:
    token = _TEST_CONTEXTVAR.set(value)
    try:
        yield
    finally:
        _TEST_CONTEXTVAR.reset(token)


async def test_context_propagation():
    server = MCPServer("test")

    @server.tool()
    async def check_context() -> str:
        """Return the contextvar value visible to the handler."""
        return _TEST_CONTEXTVAR.get()

    async with Client(server) as client:
        with _set_test_contextvar("client_value"):
            result = await client.call_tool("check_context", {})

    assert result.content[0].text == "client_value", (  # type: ignore[union-attr]
        "Server handler did not see the sender's contextvars.Context"
    )


async def test_client_auto_mode_probes_discover_then_adopts(simple_server: Server) -> None:
    """Runs over HTTP because the in-memory runner gates `server/discover` behind the init handshake."""
    with anyio.fail_after(5):
        async with (
            mounted_app(simple_server) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto") as client,
        ):
            assert client.protocol_version == "2026-07-28"
            assert (await client.list_resources()).resources[0].name == "Test Resource"


@pytest.mark.parametrize("code", [types.METHOD_NOT_FOUND, types.REQUEST_TIMEOUT, types.INTERNAL_ERROR])
async def test_client_auto_mode_falls_back_to_initialize_on_legacy_signal(code: int) -> None:
    """Any rpc-error from `server/discover` reads as "not modern" — even INTERNAL_ERROR, since a legacy server
    may crash on the unknown method. A real `Server` always implements `server/discover`, so it's hand-played."""
    methods_seen: list[str] = []

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        async for message in server_read:
            assert isinstance(message, SessionMessage)
            frame = message.message
            assert isinstance(frame, types.JSONRPCRequest | types.JSONRPCNotification)
            methods_seen.append(frame.method)
            if isinstance(frame, types.JSONRPCNotification):
                continue
            if frame.method == "server/discover":
                error = types.ErrorData(code=code, message="nope")
                await server_write.send(SessionMessage(types.JSONRPCError(jsonrpc="2.0", id=frame.id, error=error)))
            elif frame.method == "initialize":  # pragma: no branch
                result = types.InitializeResult(
                    protocol_version=LATEST_HANDSHAKE_VERSION,
                    capabilities=ServerCapabilities(),
                    server_info=types.Implementation(name="legacy-only", version="0.0.1"),
                )
                await server_write.send(
                    SessionMessage(
                        types.JSONRPCResponse(
                            jsonrpc="2.0",
                            id=frame.id,
                            result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                        )
                    )
                )

    @asynccontextmanager
    async def scripted_transport() -> AsyncIterator[TransportStreams]:
        async with (
            create_client_server_memory_streams() as ((client_read, client_write), server_streams),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(scripted_server, server_streams)
            yield client_read, client_write
            tg.cancel_scope.cancel()

    with anyio.fail_after(5):
        async with Client(scripted_transport(), mode="auto") as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION
            assert client.server_info.name == "legacy-only"
    assert methods_seen == ["server/discover", "initialize", "notifications/initialized"]


@pytest.mark.anyio
async def test_modern_list_tools_drops_tools_with_invalid_x_mcp_header_but_legacy_does_not() -> None:
    """The 2026-07-28 spec requires excluding tools with a malformed `x-mcp-header`; handshake-era sessions don't."""
    valid = types.Tool(
        name="ok",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "Region"}}},
    )
    bad = types.Tool(
        name="dropme",
        input_schema={"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}},
    )

    async def on_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[valid, bad])

    server = Server("test", on_list_tools=on_list_tools)

    with anyio.fail_after(5):
        async with Client(server) as client:
            result = await client.list_tools()
        assert [t.name for t in result.tools] == ["ok"]

        async with Client(server, mode="legacy") as client:
            result = await client.list_tools()
        assert [t.name for t in result.tools] == ["ok", "dropme"]


def test_client_rejects_handshake_era_mode_at_construction() -> None:
    server = MCPServer("test")
    with pytest.raises(ValueError, match=r"handshake-era version; use mode='legacy'"):
        Client(server, mode="2025-06-18")
    with pytest.raises(ValueError, match=r"mode must be 'legacy', 'auto', or one of"):
        Client(server, mode="not-a-version")


_NAME_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


def _name_elicitation(message: str = "What is your name?") -> types.ElicitRequest:
    return types.ElicitRequest(params=types.ElicitRequestFormParams(message=message, requested_schema=_NAME_SCHEMA))


async def test_call_tool_auto_loop_dispatches_elicitation_then_returns_final_result() -> None:
    """SEP-2322 auto-loop: `call_tool` routes the `InputRequiredResult` to `elicitation_callback` and retries."""
    server = MCPServer("test")

    @server.tool()
    async def greet(ctx: Context) -> str | types.InputRequiredResult:
        responses = ctx.input_responses
        if responses and "user_name" in responses:
            answer = responses["user_name"]
            assert isinstance(answer, types.ElicitResult)
            assert answer.content is not None
            return f"Hello, {answer.content['name']}!"
        return types.InputRequiredResult(input_requests={"user_name": _name_elicitation()})

    callback_params: list[types.ElicitRequestParams] = []

    async def elicitation_callback(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        callback_params.append(params)
        assert context.request_id == "user_name"  # the inputRequests key is the request id
        return types.ElicitResult(action="accept", content={"name": "Ada"})

    with anyio.fail_after(5):
        async with Client(server, elicitation_callback=elicitation_callback) as client:
            result = await client.call_tool("greet")

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="Hello, Ada!")], structured_content={"result": "Hello, Ada!"})
    )
    assert len(callback_params) == 1
    assert isinstance(callback_params[0], types.ElicitRequestFormParams)
    assert callback_params[0].message == "What is your name?"
    assert callback_params[0].requested_schema == _NAME_SCHEMA


async def test_call_tool_auto_loop_dispatches_sampling_then_returns_final_result() -> None:
    server = MCPServer("test")

    @server.tool()
    async def ask(ctx: Context) -> str | types.InputRequiredResult:
        responses = ctx.input_responses
        if responses and "q" in responses:
            answer = responses["q"]
            assert isinstance(answer, types.CreateMessageResult)
            assert answer.content.type == "text"
            return f"Model said: {answer.content.text}"
        return types.InputRequiredResult(
            input_requests={
                "q": types.CreateMessageRequest(
                    params=types.CreateMessageRequestParams(
                        messages=[types.SamplingMessage(role="user", content=TextContent(text="Capital of France?"))],
                        max_tokens=10,
                    )
                )
            }
        )

    callback_params: list[types.CreateMessageRequestParams] = []

    async def sampling_callback(
        context: ClientRequestContext, params: types.CreateMessageRequestParams
    ) -> types.CreateMessageResult | types.ErrorData:
        callback_params.append(params)
        return types.CreateMessageResult(role="assistant", content=TextContent(text="Paris"), model="echo")

    with anyio.fail_after(5):
        async with Client(server, sampling_callback=sampling_callback) as client:
            result = await client.call_tool("ask")

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="Model said: Paris")], structured_content={"result": "Model said: Paris"}
        )
    )
    assert len(callback_params) == 1
    assert callback_params[0].messages[0].content == TextContent(text="Capital of France?")


async def test_call_tool_auto_loop_dispatches_list_roots_then_returns_final_result() -> None:
    server = MCPServer("test")

    @server.tool()
    async def count_roots(ctx: Context) -> str | types.InputRequiredResult:
        responses = ctx.input_responses
        if responses and "roots" in responses:
            answer = responses["roots"]
            assert isinstance(answer, types.ListRootsResult)
            return f"Client exposed {len(answer.roots)} root(s)."
        return types.InputRequiredResult(input_requests={"roots": types.ListRootsRequest()})

    callback_called: list[ClientRequestContext] = []

    async def list_roots_callback(context: ClientRequestContext) -> types.ListRootsResult | types.ErrorData:
        callback_called.append(context)
        return types.ListRootsResult(roots=[types.Root(uri=FileUrl("file:///workspace"))])

    with anyio.fail_after(5):
        async with Client(server, list_roots_callback=list_roots_callback) as client:
            result = await client.call_tool("count_roots")

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(text="Client exposed 1 root(s).")],
            structured_content={"result": "Client exposed 1 root(s)."},
        )
    )
    assert len(callback_called) == 1
    assert callback_called[0].request_id == "roots"


async def test_call_tool_auto_loop_round_trips_evolving_request_state_across_three_rounds() -> None:
    """The driver must echo each round's `request_state` back to the server byte-exact."""
    server = MCPServer("test")

    @server.tool()
    async def multi(ctx: Context) -> str | types.InputRequiredResult:
        round_num = int(ctx.request_state) if ctx.request_state else 0
        if round_num == 3:
            return "done after 3 rounds"
        next_round = round_num + 1
        return types.InputRequiredResult(
            input_requests={f"step{next_round}": _name_elicitation(f"Round {next_round}?")},
            request_state=str(next_round),
        )

    messages: list[str] = []

    async def elicitation_callback(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        assert isinstance(params, types.ElicitRequestFormParams)
        messages.append(params.message)
        return types.ElicitResult(action="accept", content={"name": "x"})

    with anyio.fail_after(5):
        async with Client(server, elicitation_callback=elicitation_callback) as client:
            result = await client.call_tool("multi")

    assert result.content == [TextContent(text="done after 3 rounds")]
    assert messages == ["Round 1?", "Round 2?", "Round 3?"]


async def test_call_tool_auto_loop_raises_mcp_error_when_no_callback_registered() -> None:
    """SDK-defined: the default callback returns `ErrorData(INVALID_REQUEST)`, raised as `MCPError`, no retry."""
    server = MCPServer("test")

    @server.tool()
    async def needs_input(ctx: Context) -> str | types.InputRequiredResult:
        if ctx.input_responses:
            raise NotImplementedError  # unreachable: client errors before retrying
        return types.InputRequiredResult(input_requests={"ask": _name_elicitation()})

    async with Client(server) as client:
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.call_tool("needs_input")
    assert exc.value.error.code == types.INVALID_REQUEST


async def test_get_prompt_auto_loop_resolves_input_required_via_callbacks() -> None:
    async def handler(
        ctx: ServerRequestContext, params: types.GetPromptRequestParams
    ) -> types.GetPromptResult | types.InputRequiredResult:
        assert params.name == "summary"
        if params.input_responses and "ask" in params.input_responses:
            return GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="ok"))])
        return types.InputRequiredResult(input_requests={"ask": _name_elicitation()})

    server = Server("test")
    server.add_request_handler("prompts/get", types.GetPromptRequestParams, handler)

    async def elicitation_callback(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        return types.ElicitResult(action="accept", content={"name": "x"})

    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28", elicitation_callback=elicitation_callback) as client:
            result = await client.get_prompt("summary")
    assert result == snapshot(GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="ok"))]))


async def test_read_resource_auto_loop_resolves_input_required_via_callbacks() -> None:
    async def handler(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult | types.InputRequiredResult:
        assert params.uri == "memory://gated"
        if params.input_responses and "ask" in params.input_responses:
            return ReadResourceResult(contents=[TextResourceContents(uri="memory://gated", text="unlocked")])
        return types.InputRequiredResult(input_requests={"ask": _name_elicitation()})

    server = Server("test")
    server.add_request_handler("resources/read", types.ReadResourceRequestParams, handler)

    async def elicitation_callback(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        return types.ElicitResult(action="accept", content={"name": "x"})

    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28", elicitation_callback=elicitation_callback) as client:
            result = await client.read_resource("memory://gated")
    assert result == snapshot(
        ReadResourceResult(contents=[TextResourceContents(uri="memory://gated", text="unlocked")])
    )
