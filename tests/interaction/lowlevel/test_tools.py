"""Tool interactions against the low-level Server, driven through the public Client API."""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
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

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")]))


@requirement("tools:call:is-error")
async def test_call_tool_execution_error_is_returned_as_result(connect: Connect) -> None:
    """Execution errors are part of the result so the caller (typically a model) can see them.

    Only protocol-level failures become JSON-RPC errors.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "flux"
        return CallToolResult(content=[TextContent(text="the flux capacitor is offline")], is_error=True)

    server = Server("errors", on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("flux", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="the flux capacitor is offline")], is_error=True)
    )


@requirement("tools:call:unknown-name")
async def test_call_tool_unknown_tool_is_protocol_error(connect: Connect) -> None:
    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown tool: {params.name}", data={"requested": params.name})

    server = Server("errors", on_call_tool=call_tool)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("nope", {})

    assert exc_info.value.error == snapshot(
        ErrorData(code=INVALID_PARAMS, message="Unknown tool: nope", data={"requested": "nope"})
    )


@requirement("protocol:error:internal-error")
async def test_call_tool_uncaught_exception_becomes_error_response(connect: Connect) -> None:
    """The low-level server reports code 0 with the exception text; see the divergence note on the requirement."""

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "explode"
        raise ValueError("boom")

    server = Server("errors", on_call_tool=call_tool)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("explode", {})

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="boom"))


@requirement("tools:list:basic")
async def test_list_tools_returns_registered_tools(connect: Connect) -> None:
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

    async with connect(server) as client:
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


@requirement("tools:input-schema:json-schema-2020-12")
@requirement("tools:input-schema:preserve-additional-properties")
@requirement("tools:input-schema:preserve-defs")
@requirement("tools:input-schema:preserve-schema-dialect")
async def test_tools_list_preserves_arbitrary_input_schema_keywords(connect: Connect) -> None:
    """The single identity assertion proves all four pass-through requirements at once.

    The registered schema dict arrives unchanged, so $schema, $defs, nested objects, and
    additionalProperties each survive.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "$defs": {"positive": {"type": "integer", "exclusiveMinimum": 0}},
        "properties": {
            "count": {"$ref": "#/$defs/positive"},
            "options": {
                "type": "object",
                "properties": {"verbose": {"type": "boolean"}},
                "additionalProperties": False,
            },
        },
        "required": ["count"],
        "additionalProperties": False,
    }

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="typed", input_schema=schema)])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "typed"
        assert params.arguments == {"count": 3, "options": {"verbose": True}}
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("typed", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        listed = await client.list_tools()
        called = await client.call_tool("typed", {"count": 3, "options": {"verbose": True}})

    assert listed.tools[0].input_schema == schema
    assert called == snapshot(CallToolResult(content=[TextContent(text="ok")]))


@requirement("tools:list:metadata")
async def test_list_tools_optional_fields_round_trip(connect: Connect) -> None:
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

    async with connect(server) as client:
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


@requirement("tools:call:content:mixed")
@requirement("tools:call:content:image")
@requirement("tools:call:content:audio")
@requirement("tools:call:content:resource-link")
@requirement("tools:call:content:embedded-resource")
async def test_call_tool_multiple_content_block_types(connect: Connect) -> None:
    """The fixed base64 payloads ("aW1n" is b"img", "YXVk" is b"aud") let the snapshot pin the exact bytes."""

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

    async with connect(server) as client:
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
async def test_call_tool_structured_content(connect: Connect) -> None:
    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="sum", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "sum"
        return CallToolResult(content=[TextContent(text="the sum is 5")], structured_content={"sum": 5})

    server = Server("calculator", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("sum", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="the sum is 5")], structured_content={"sum": 5}))


@requirement("tools:call:concurrent")
async def test_concurrent_tool_calls_complete_independently(connect: Connect) -> None:
    """Both handlers are held on a shared event until both have signalled they started.

    A sequential server would never start the second handler and the test would time out.
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

    async with connect(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:  # pragma: no branch

                async def call_and_record(tag: str) -> None:
                    results[tag] = await client.call_tool("echo", {"tag": tag})

                task_group.start_soon(call_and_record, "first")
                task_group.start_soon(call_and_record, "second")

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


@requirement("client:output-schema:validate")
async def test_call_tool_structured_content_violating_output_schema_is_rejected_by_the_client(connect: Connect) -> None:
    """The client validates structured content against the output schema cached from tools/list and raises."""

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

    async with connect(server) as client:
        await client.list_tools()
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("forecast", {})

    # The message embeds the jsonschema validation error, so only the SDK-authored prefix is pinned.
    assert str(exc_info.value).startswith("Invalid structured content returned by tool forecast")


@requirement("client:output-schema:skip-on-error")
async def test_is_error_result_bypasses_client_output_schema_validation(connect: Connect) -> None:
    """The schema is cached up front, proving the bypass is specifically the isError flag, not an empty cache."""

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
        return CallToolResult(
            content=[TextContent(text="boom")], structured_content={"temperature": "warm"}, is_error=True
        )

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        result = await client.call_tool("forecast", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(text="boom")], structured_content={"temperature": "warm"}, is_error=True)
    )


@requirement("client:output-schema:missing-structured")
async def test_declared_output_schema_with_no_structured_content_is_rejected_by_the_client(connect: Connect) -> None:
    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    input_schema={"type": "object"},
                    output_schema={"type": "object", "properties": {"temperature": {"type": "number"}}},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "forecast"
        return CallToolResult(content=[TextContent(text="warm")])

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("forecast", {})

    assert str(exc_info.value) == snapshot("Tool forecast has an output schema but did not return structured content")


@requirement("client:output-schema:auto-list")
async def test_call_tool_populates_the_output_schema_cache_via_an_implicit_tools_list(connect: Connect) -> None:
    """The first call of an uncached tool issues one implicit tools/list; the second hits the cache.

    This is why a server with only on_call_tool sees a successful call answered with
    METHOD_NOT_FOUND from a request the caller never made; see the divergence on the requirement.
    """
    list_calls: list[str] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        list_calls.append("called")
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    input_schema={"type": "object"},
                    output_schema={"type": "object", "properties": {"temperature": {"type": "number"}}},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "forecast"
        return CallToolResult(content=[TextContent(text="21 C")], structured_content={"temperature": 21})

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        first = await client.call_tool("forecast", {})
        assert list_calls == ["called"]
        second = await client.call_tool("forecast", {})

    assert list_calls == ["called"]
    assert first == snapshot(CallToolResult(content=[TextContent(text="21 C")], structured_content={"temperature": 21}))
    assert second == first
