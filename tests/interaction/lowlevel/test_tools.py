"""Tool interactions against the low-level Server, driven through the public Client API."""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    INVALID_PARAMS,
    AudioContent,
    CallToolResult,
    EmbeddedResource,
    ErrorData,
    Icon,
    ImageContent,
    ListToolsResult,
    ResourceLink,
    TextContent,
    TextResourceContents,
    Tool,
    ToolAnnotations,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content() -> None:
    """Arguments reach the tool handler; its content comes back as the call result."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="add", description="Add two integers.", input_schema={"type": "object"})]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "add"
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["a"] + params.arguments["b"]))])

    server = Server("adder", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")]))


@requirement("tools:call:is-error")
async def test_call_tool_execution_error_is_returned_as_result() -> None:
    """A tool reporting its own failure with is_error=True reaches the client as a result, not an exception.

    Tool execution errors are part of the result so the caller (typically a model) can see
    them; only protocol-level failures become JSON-RPC errors.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "flux"
        return CallToolResult(content=[TextContent(text="the flux capacitor is offline")], is_error=True)

    server = Server("errors", on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("flux", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="the flux capacitor is offline")], is_error=True)
    )


@requirement("tools:call:unknown-name")
async def test_call_tool_unknown_tool_is_protocol_error() -> None:
    """A handler that rejects an unrecognised tool name with MCPError produces a JSON-RPC error.

    The error's code, message, and data chosen by the handler reach the client verbatim.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown tool: {params.name}", data={"requested": params.name})

    server = Server("errors", on_call_tool=call_tool)

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("nope", {})

    assert exc_info.value.error == snapshot(
        ErrorData(code=INVALID_PARAMS, message="Unknown tool: nope", data={"requested": "nope"})
    )


@requirement("protocol:error:internal-error")
async def test_call_tool_uncaught_exception_becomes_error_response() -> None:
    """An uncaught exception in the tool handler surfaces to the client as a JSON-RPC error.

    The low-level server reports it with code 0 and the exception text as the message; see the
    divergence note on the requirement.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "explode"
        raise ValueError("boom")

    server = Server("errors", on_call_tool=call_tool)

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("explode", {})

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="boom"))


@requirement("tools:list:basic")
async def test_list_tools_returns_registered_tools() -> None:
    """The tools advertised by the server's list handler arrive at the client unchanged."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="add",
                    description="Add two integers.",
                    input_schema={
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                    },
                ),
                Tool(name="reset", description="Reset the calculator.", input_schema={"type": "object"}),
            ]
        )

    server = Server("calculator", on_list_tools=list_tools)

    async with Client(server) as client:
        result = await client.list_tools()

    assert result == snapshot(
        ListToolsResult(
            tools=[
                Tool(
                    name="add",
                    description="Add two integers.",
                    input_schema={
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                    },
                ),
                Tool(name="reset", description="Reset the calculator.", input_schema={"type": "object"}),
            ]
        )
    )


@requirement("tools:list:optional-fields")
async def test_list_tools_optional_fields_round_trip() -> None:
    """Every optional Tool field the server supplies reaches the client unchanged."""

    tool = Tool(
        name="annotated",
        title="Annotated tool",
        description="A tool carrying every optional field.",
        input_schema={"type": "object"},
        output_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
        icons=[Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48"])],
        annotations=ToolAnnotations(title="Display title", read_only_hint=True, idempotent_hint=True),
        _meta={"example.com/source": "interaction-suite"},
    )

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[tool])

    server = Server("annotated", on_list_tools=list_tools)

    async with Client(server) as client:
        result = await client.list_tools()

    assert result == snapshot(
        ListToolsResult(
            tools=[
                Tool(
                    name="annotated",
                    title="Annotated tool",
                    description="A tool carrying every optional field.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
                    icons=[Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48"])],
                    annotations=ToolAnnotations(title="Display title", read_only_hint=True, idempotent_hint=True),
                    _meta={"example.com/source": "interaction-suite"},
                )
            ]
        )
    )


@requirement("tools:call:content:multiple")
@requirement("tools:call:content:image")
@requirement("tools:call:content:audio")
@requirement("tools:call:content:resource-link")
@requirement("tools:call:content:embedded-resource")
async def test_call_tool_multiple_content_block_types() -> None:
    """A tool result can mix every content block type; all of them arrive in order.

    The payloads are tiny fixed base64 strings ("aW1n" is b"img", "YXVk" is b"aud") so the
    snapshot pins the exact bytes the client receives.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="render", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "render"
        return CallToolResult(
            content=[
                TextContent(text="all five content block types"),
                ImageContent(data="aW1n", mime_type="image/png"),
                AudioContent(data="YXVk", mime_type="audio/wav"),
                ResourceLink(name="report", uri="resource://reports/1", description="The full report"),
                EmbeddedResource(
                    resource=TextResourceContents(uri="resource://reports/1", mime_type="text/plain", text="contents")
                ),
            ]
        )

    server = Server("renderer", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("render", {})

    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(text="all five content block types"),
                ImageContent(data="aW1n", mime_type="image/png"),
                AudioContent(data="YXVk", mime_type="audio/wav"),
                ResourceLink(name="report", uri="resource://reports/1", description="The full report"),
                EmbeddedResource(
                    resource=TextResourceContents(uri="resource://reports/1", mime_type="text/plain", text="contents")
                ),
            ]
        )
    )


@requirement("tools:call:structured-content")
async def test_call_tool_structured_content() -> None:
    """A tool result carrying structured content alongside content delivers both to the client."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="sum", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "sum"
        return CallToolResult(content=[TextContent(text="the sum is 5")], structured_content={"sum": 5})

    server = Server("calculator", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        result = await client.call_tool("sum", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="the sum is 5")], structured_content={"sum": 5}))


@requirement("tools:call:concurrent")
async def test_concurrent_tool_calls_complete_independently() -> None:
    """Two tool calls in flight at once run concurrently and each caller gets its own answer.

    Both handlers are held on a shared event after signalling that they have started, and the test
    only releases them once both signals have arrived -- a server that processed requests
    sequentially would never start the second handler and the test would time out instead.
    """
    started: list[str] = []
    started_events = {"first": anyio.Event(), "second": anyio.Event()}
    release = anyio.Event()
    results: dict[str, CallToolResult] = {}

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        assert params.arguments is not None
        tag = params.arguments["tag"]
        assert isinstance(tag, str)
        started.append(tag)
        started_events[tag].set()
        await release.wait()
        return CallToolResult(content=[TextContent(text=tag)])

    server = Server("echoer", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:

                async def call_and_record(tag: str) -> None:
                    results[tag] = await client.call_tool("echo", {"tag": tag})

                task_group.start_soon(call_and_record, "first")
                task_group.start_soon(call_and_record, "second")

                # Both handlers are running at the same time before either is allowed to finish.
                await started_events["first"].wait()
                await started_events["second"].wait()
                release.set()

    assert sorted(started) == ["first", "second"]
    assert results == snapshot(
        {
            "first": CallToolResult(content=[TextContent(text="first")]),
            "second": CallToolResult(content=[TextContent(text="second")]),
        }
    )


@requirement("tools:call:output-schema-validation")
async def test_call_tool_structured_content_violating_output_schema_is_rejected_by_the_client() -> None:
    """A result whose structured content does not conform to the tool's declared output schema never
    reaches the caller: the client validates it against the schema cached from tools/list and raises.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    input_schema={"type": "object"},
                    output_schema={
                        "type": "object",
                        "properties": {"temperature": {"type": "number"}},
                        "required": ["temperature"],
                    },
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "forecast"
        return CallToolResult(content=[TextContent(text="warm")], structured_content={"temperature": "warm"})

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server) as client:
        await client.list_tools()
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("forecast", {})

    # The message embeds the jsonschema validation error, so only the SDK-authored prefix is pinned.
    assert str(exc_info.value).startswith("Invalid structured content returned by tool forecast")
