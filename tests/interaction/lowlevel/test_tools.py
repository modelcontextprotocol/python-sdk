"""Tool interactions against the low-level Server, driven through the public Client API."""

from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import McpError, types
from mcp.server.lowlevel import Server
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
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content(connect: Connect) -> None:
    """Arguments reach the tool handler; its content comes back as the call result."""
    server = Server("adder")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name="add", description="Add two integers.", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "add"
        return CallToolResult(content=[TextContent(type="text", text=str(arguments["a"] + arguments["b"]))])

    async with connect(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="5")]))


@requirement("tools:call:is-error")
async def test_call_tool_execution_error_is_returned_as_result(connect: Connect) -> None:
    """A tool reporting its own failure with isError=True reaches the client as a result, not an exception.

    Tool execution errors are part of the result so the caller (typically a model) can see
    them; only protocol-level failures become JSON-RPC errors.
    """
    server = Server("errors")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "flux"
        return CallToolResult(content=[TextContent(type="text", text="the flux capacitor is offline")], isError=True)

    async with connect(server) as client:
        result = await client.call_tool("flux", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(type="text", text="the flux capacitor is offline")], isError=True)
    )


@requirement("tools:call:unknown-name")
async def test_call_tool_unknown_tool_is_protocol_error(connect: Connect) -> None:
    """A handler that rejects an unrecognised tool name with McpError is swallowed into an isError result.

    On v1 the lowlevel `@server.call_tool()` decorator catches every handler exception (including
    `McpError`) and converts it to `CallToolResult(isError=True, content=[TextContent(text=str(exc))])`,
    so the handler cannot produce a protocol-level JSON-RPC error for this method. See the
    divergence note on the requirement.
    """
    server = Server("errors")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown tool: {name}", data={"requested": name}))

    async with connect(server) as client:
        result = await client.call_tool("nope", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(type="text", text="Unknown tool: nope")], isError=True)
    )


@requirement("protocol:error:internal-error")
async def test_call_tool_uncaught_exception_becomes_error_response(connect: Connect) -> None:
    """An uncaught exception in a tool handler is swallowed into an isError=True result.

    On v1 the lowlevel `@server.call_tool()` decorator wraps the handler in a broad try/except
    that converts every `Exception` to `CallToolResult(isError=True, content=[TextContent(text=str(exc))])`,
    so the dispatcher's JSON-RPC error path is never reached for tool calls. See the divergence
    note on the requirement.
    """
    server = Server("errors")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        assert name == "explode"
        raise ValueError("boom")

    async with connect(server) as client:
        result = await client.call_tool("explode", {})

    assert result == snapshot(CallToolResult(content=[TextContent(type="text", text="boom")], isError=True))


@requirement("tools:list:basic")
async def test_list_tools_returns_registered_tools(connect: Connect) -> None:
    """The tools advertised by the server's list handler arrive at the client unchanged."""
    server = Server("calculator")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="add",
                description="Add two integers.",
                inputSchema={
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            ),
            Tool(name="reset", description="Reset the calculator.", inputSchema={"type": "object"}),
        ]

    async with connect(server) as client:
        result = await client.list_tools()

    assert result == snapshot(
        ListToolsResult(
            tools=[
                Tool(
                    name="add",
                    description="Add two integers.",
                    inputSchema={
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                    },
                ),
                Tool(name="reset", description="Reset the calculator.", inputSchema={"type": "object"}),
            ]
        )
    )


@requirement("tools:input-schema:json-schema-2020-12")
@requirement("tools:input-schema:preserve-additional-properties")
@requirement("tools:input-schema:preserve-defs")
@requirement("tools:input-schema:preserve-schema-dialect")
async def test_tools_list_preserves_arbitrary_input_schema_keywords(connect: Connect) -> None:
    """A rich JSON Schema 2020-12 inputSchema reaches the client unchanged and the tool is callable.

    The single identity assertion below proves all four pass-through behaviours at once: the same
    dict literal that was registered is the dict that arrives, so $schema, $defs, the nested object
    property, and additionalProperties are each preserved by virtue of the whole schema being
    preserved. The follow-up call proves the rich-schema tool is callable end to end.
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

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(tools=[Tool(name="typed", inputSchema=schema)])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "typed"
        assert params.arguments == {"count": 3, "options": {"verbose": True}}
        return CallToolResult(content=[TextContent(type="text", text="ok")])

    server = Server("typed", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        listed = await client.list_tools()
        called = await client.call_tool("typed", {"count": 3, "options": {"verbose": True}})

    assert listed.tools[0].input_schema == schema
    assert called == snapshot(CallToolResult(content=[TextContent(type="text", text="ok")]))


@requirement("tools:list:metadata")
async def test_list_tools_optional_fields_round_trip(connect: Connect) -> None:
    """Every optional Tool field the server supplies reaches the client unchanged."""

    tool = Tool(
        name="annotated",
        title="Annotated tool",
        description="A tool carrying every optional field.",
        inputSchema={"type": "object"},
        outputSchema={"type": "object", "properties": {"answer": {"type": "integer"}}},
        icons=[Icon(src="https://example.com/icon.png", mimeType="image/png", sizes=["48x48"])],
        annotations=ToolAnnotations(title="Display title", readOnlyHint=True, idempotentHint=True),
        _meta={"example.com/source": "interaction-suite"},
    )

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
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
                    inputSchema={"type": "object"},
                    outputSchema={"type": "object", "properties": {"answer": {"type": "integer"}}},
                    icons=[Icon(src="https://example.com/icon.png", mimeType="image/png", sizes=["48x48"])],
                    annotations=ToolAnnotations(title="Display title", readOnlyHint=True, idempotentHint=True),
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
    """A tool result can mix every content block type; all of them arrive in order.

    The payloads are tiny fixed base64 strings ("aW1n" is b"img", "YXVk" is b"aud") so the
    snapshot pins the exact bytes the client receives.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(tools=[Tool(name="render", inputSchema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "render"
        return CallToolResult(
            content=[
                TextContent(type="text", text="all five content block types"),
                ImageContent(type="image", data="aW1n", mimeType="image/png"),
                AudioContent(type="audio", data="YXVk", mimeType="audio/wav"),
                ResourceLink(
                    type="resource_link", name="report", uri="resource://reports/1", description="The full report"
                ),
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(uri="resource://reports/1", mimeType="text/plain", text="contents"),
                ),
            ]
        )

    server = Server("renderer", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("render", {})

    assert result == snapshot(
        CallToolResult(
            content=[
                TextContent(type="text", text="all five content block types"),
                ImageContent(type="image", data="aW1n", mimeType="image/png"),
                AudioContent(type="audio", data="YXVk", mimeType="audio/wav"),
                ResourceLink(
                    type="resource_link", name="report", uri="resource://reports/1", description="The full report"
                ),
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(uri="resource://reports/1", mimeType="text/plain", text="contents"),
                ),
            ]
        )
    )


@requirement("tools:call:structured-content")
async def test_call_tool_structured_content(connect: Connect) -> None:
    """A tool result carrying structured content alongside content delivers both to the client."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(tools=[Tool(name="sum", inputSchema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "sum"
        return CallToolResult(content=[TextContent(type="text", text="the sum is 5")], structuredContent={"sum": 5})

    server = Server("calculator", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("sum", {})

    assert result == snapshot(
        CallToolResult(content=[TextContent(type="text", text="the sum is 5")], structuredContent={"sum": 5})
    )


@requirement("tools:call:concurrent")
async def test_concurrent_tool_calls_complete_independently(connect: Connect) -> None:
    """Two tool calls in flight at once run concurrently and each caller gets its own answer.

    Both handlers are held on a shared event after signalling that they have started, and the test
    only releases them once both signals have arrived -- a server that processed requests
    sequentially would never start the second handler and the test would time out instead.
    """
    started: list[str] = []
    started_events = {"first": anyio.Event(), "second": anyio.Event()}
    release = anyio.Event()
    results: dict[str, CallToolResult] = {}

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(tools=[Tool(name="echo", inputSchema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "echo"
        assert params.arguments is not None
        tag = params.arguments["tag"]
        assert isinstance(tag, str)
        started.append(tag)
        started_events[tag].set()
        await release.wait()
        return CallToolResult(content=[TextContent(type="text", text=tag)])

    server = Server("echoer", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:  # pragma: no branch

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
            "first": CallToolResult(content=[TextContent(type="text", text="first")]),
            "second": CallToolResult(content=[TextContent(type="text", text="second")]),
        }
    )


@requirement("client:output-schema:validate")
async def test_call_tool_structured_content_violating_output_schema_is_rejected_by_the_client(connect: Connect) -> None:
    """A result whose structured content does not conform to the tool's declared output schema never
    reaches the caller: the client validates it against the schema cached from tools/list and raises.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    inputSchema={"type": "object"},
                    outputSchema={
                        "type": "object",
                        "properties": {"temperature": {"type": "number"}},
                        "required": ["temperature"],
                    },
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "forecast"
        return CallToolResult(
            content=[TextContent(type="text", text="warm")], structuredContent={"temperature": "warm"}
        )

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("forecast", {})

    # The message embeds the jsonschema validation error, so only the SDK-authored prefix is pinned.
    assert str(exc_info.value).startswith("Invalid structured content returned by tool forecast")


@requirement("client:output-schema:skip-on-error")
async def test_is_error_result_bypasses_client_output_schema_validation(connect: Connect) -> None:
    """A tool result with isError true is returned as-is even when its structured content violates the schema.

    The schema is cached up front so the client could validate, proving the bypass is specifically the
    isError flag and not an empty cache.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    inputSchema={"type": "object"},
                    outputSchema={
                        "type": "object",
                        "properties": {"temperature": {"type": "number"}},
                        "required": ["temperature"],
                    },
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "forecast"
        return CallToolResult(
            content=[TextContent(type="text", text="boom")], structuredContent={"temperature": "warm"}, isError=True
        )

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        result = await client.call_tool("forecast", {})

    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="boom")], structuredContent={"temperature": "warm"}, isError=True
        )
    )


@requirement("client:output-schema:missing-structured")
async def test_declared_output_schema_with_no_structured_content_is_rejected_by_the_client(connect: Connect) -> None:
    """A tool that declared an output schema but returned no structuredContent fails the client-side check.

    The error is the SDK's own message, so the full text is snapshotted.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    inputSchema={"type": "object"},
                    outputSchema={"type": "object", "properties": {"temperature": {"type": "number"}}},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "forecast"
        return CallToolResult(content=[TextContent(type="text", text="warm")])

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("forecast", {})

    assert str(exc_info.value) == snapshot("Tool forecast has an output schema but did not return structured content")


@requirement("client:output-schema:auto-list")
async def test_call_tool_populates_the_output_schema_cache_via_an_implicit_tools_list(connect: Connect) -> None:
    """Calling a tool whose schema is not cached issues exactly one implicit tools/list to populate it.

    The first call_tool of an uncached tool triggers a tools/list the caller never asked for; the
    second call hits the cache and does not. This is the SDK's chosen cache strategy and the cause of
    the surprising behaviour where a server with only on_call_tool sees a successful call answered
    with METHOD_NOT_FOUND from a request the caller never made; see the divergence on the requirement.
    """
    list_calls: list[str] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:  # noqa: F821 -- batch 2/3 rewrites this body
        list_calls.append("called")
        return ListToolsResult(
            tools=[
                Tool(
                    name="forecast",
                    inputSchema={"type": "object"},
                    outputSchema={"type": "object", "properties": {"temperature": {"type": "number"}}},
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:  # noqa: F821 -- batch 2/3 rewrites this body
        assert params.name == "forecast"
        return CallToolResult(content=[TextContent(type="text", text="21 C")], structuredContent={"temperature": 21})

    server = Server("weather", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        first = await client.call_tool("forecast", {})
        assert list_calls == ["called"]
        second = await client.call_tool("forecast", {})

    assert list_calls == ["called"]
    assert first == snapshot(
        CallToolResult(content=[TextContent(type="text", text="21 C")], structuredContent={"temperature": 21})
    )
    assert second == first
