"""Tool interactions against the low-level Server, driven through the public Client API."""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    AudioContent,
    CallToolResult,
    DiscoverResult,
    EmbeddedResource,
    ErrorData,
    Icon,
    ImageContent,
    Implementation,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    ResourceLink,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
    ToolAnnotations,
)
from mcp_types.version import LATEST_MODERN_VERSION

from mcp import MCPError
from mcp.client.session import ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

# Shared by the client:jsonschema:* tests. prefixItems is enforced under JSON Schema 2020-12 but
# ignored under draft-07, so one schema/value pair reveals which engine validated it.
_PREFIX_ITEMS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"point": {"type": "array", "prefixItems": [{"type": "number"}, {"type": "number"}]}},
    "required": ["point"],
}
_CONFORMING_POINT = {"point": [1.5, 2.5]}
_VIOLATING_POINT = {"point": [1, "x"]}  # index 1 violates the second prefixItems schema
_INTS_SCHEMA: dict[str, object] = {"type": "array", "items": {"type": "integer"}}


@requirement("tools:call:content:text")
async def test_call_tool_returns_text_content(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result == snapshot(CallToolResult(content=[TextContent(text="5")]))


@requirement("tools:call:is-error")
async def test_call_tool_execution_error_is_returned_as_result(connect: Connect) -> None:
    """A tool reporting its own failure with is_error=True reaches the client as a result, not an exception.

    Tool execution errors are part of the result so the caller (typically a model) can see
    them; only protocol-level failures become JSON-RPC errors.
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
    """A handler that rejects an unrecognised tool name with MCPError produces a JSON-RPC error.

    The error's code, message, and data chosen by the handler reach the client verbatim.
    """

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
    """An uncaught exception in the tool handler surfaces to the client as a JSON-RPC error.

    The low-level server reports it with code 0 and the exception text as the message; see the
    divergence note on the requirement.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "explode"
        raise ValueError("boom")

    server = Server("errors", on_call_tool=call_tool)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("explode", {})

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="boom"))


@requirement("errors:wire:legacy-code-opaque")
async def test_a_legacy_range_error_code_reaches_the_caller_verbatim_without_interpretation(
    connect: Connect,
) -> None:
    """An error code from the legacy -32000..-32019 sub-range reaches the caller verbatim with no meaning assigned."""

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "vendor"
        # -32011: an in-band legacy-range code with no defined meaning (deliberately not -32002).
        raise MCPError(code=-32011, message="vendor-specific failure", data={"hint": "opaque"})

    server = Server("errors", on_call_tool=call_tool)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("vendor", {})

    assert exc_info.value.error == snapshot(
        ErrorData(code=-32011, message="vendor-specific failure", data={"hint": "opaque"})
    )


@requirement("tools:list:basic")
async def test_list_tools_returns_registered_tools(connect: Connect) -> None:
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
    """A tool result carrying structured content alongside content delivers both to the client."""

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
            "first": CallToolResult(content=[TextContent(text="first")]),
            "second": CallToolResult(content=[TextContent(text="second")]),
        }
    )


@requirement("client:output-schema:validate")
async def test_call_tool_structured_content_violating_output_schema_is_rejected_by_the_client(connect: Connect) -> None:
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
    """A tool that declared an output schema but returned no structuredContent fails the client-side check.

    The error is the SDK's own message, so the full text is snapshotted.
    """

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
    """Calling a tool whose schema is not cached issues exactly one implicit tools/list to populate it.

    The first call_tool of an uncached tool triggers a tools/list the caller never asked for; the
    second call hits the cache and does not. This is the SDK's chosen cache strategy and the cause of
    the surprising behaviour where a server with only on_call_tool sees a successful call answered
    with METHOD_NOT_FOUND from a request the caller never made; see the divergence on the requirement.
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


@requirement("client:jsonschema:2020-12:prefixItems")
async def test_prefix_items_in_the_output_schema_are_enforced_per_index_on_structured_content(
    connect: Connect,
) -> None:
    """A structuredContent tuple violating a prefixItems per-index schema is rejected; a conforming one returns.

    Spec-mandated (2025-11-25 onward): clients MUST support 2020-12 and SHOULD validate structured results.
    """
    schema = {**_PREFIX_ITEMS_SCHEMA, "$schema": "https://json-schema.org/draft/2020-12/schema"}

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name="coords_ok", input_schema={"type": "object"}, output_schema=schema),
                Tool(name="coords_bad", input_schema={"type": "object"}, output_schema=schema),
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name in ("coords_ok", "coords_bad")
        point = _CONFORMING_POINT if params.name == "coords_ok" else _VIOLATING_POINT
        return CallToolResult(content=[TextContent(text="point")], structured_content=point)

    server = Server("coords", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        ok = await client.call_tool("coords_ok", {})
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("coords_bad", {})

    assert ok.structured_content == _CONFORMING_POINT
    # The message embeds the jsonschema validation error, so only the SDK-authored prefix is pinned.
    assert str(exc_info.value).startswith("Invalid structured content returned by tool coords_bad")


@requirement("client:jsonschema:dialect:default-is-2020-12")
async def test_schema_dialect_defaults_to_2020_12_and_a_declared_draft_07_dialect_is_honored(
    connect: Connect,
) -> None:
    """An outputSchema without $schema is validated as 2020-12; a declared draft-07 dialect is honored.

    Spec-mandated: schemas are validated per their declared or default dialect (2025-11-25 basic).
    """
    schema_d7 = {**_PREFIX_ITEMS_SCHEMA, "$schema": "http://json-schema.org/draft-07/schema#"}

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name="untagged", input_schema={"type": "object"}, output_schema=_PREFIX_ITEMS_SCHEMA),
                Tool(name="tagged_draft7", input_schema={"type": "object"}, output_schema=schema_d7),
                Tool(name="d7_type_bad", input_schema={"type": "object"}, output_schema=schema_d7),
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name in ("untagged", "tagged_draft7", "d7_type_bad")
        if params.name == "d7_type_bad":
            # type IS enforced under draft-07, so this rejection proves validation ran under the declared dialect.
            return CallToolResult(content=[TextContent(text="point")], structured_content={"point": "xx"})
        return CallToolResult(content=[TextContent(text="point")], structured_content=_VIOLATING_POINT)

    server = Server("dialects", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        with pytest.raises(RuntimeError) as untagged_exc:
            await client.call_tool("untagged", {})
        tagged = await client.call_tool("tagged_draft7", {})
        with pytest.raises(RuntimeError) as d7_exc:
            await client.call_tool("d7_type_bad", {})

    assert str(untagged_exc.value).startswith("Invalid structured content returned by tool untagged")
    assert tagged.structured_content == _VIOLATING_POINT
    assert str(d7_exc.value).startswith("Invalid structured content returned by tool d7_type_bad")


@requirement("client:jsonschema:falsy-structured-content-validated")
async def test_falsy_structured_content_is_validated_not_mistaken_for_missing(connect: Connect) -> None:
    """Falsy structuredContent values are validated as present, not mistaken for missing.

    A falsy presence check would route all three calls to the missing-structured-content error.
    2026-only: earlier revisions restrict structuredContent to objects.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name="zero", input_schema={"type": "object"}, output_schema={"type": "integer"}),
                Tool(name="empty", input_schema={"type": "object"}, output_schema={"type": "string"}),
                Tool(name="flag", input_schema={"type": "object"}, output_schema={"type": "integer"}),
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name in ("zero", "empty", "flag")
        # flag deliberately mismatches its integer schema: JSON Schema excludes booleans from integer.
        values: dict[str, object] = {"zero": 0, "empty": "", "flag": False}
        return CallToolResult(content=[TextContent(text=params.name)], structured_content=values[params.name])

    server = Server("falsy", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        zero = await client.call_tool("zero", {})
        empty = await client.call_tool("empty", {})
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("flag", {})

    assert zero.structured_content == 0
    # False == 0 and bool subclasses int, so pin the type as well.
    assert type(zero.structured_content) is int
    assert empty.structured_content == ""
    assert str(exc_info.value).startswith("Invalid structured content returned by tool flag")


@requirement("client:jsonschema:non-object-output")
async def test_a_non_object_output_schema_root_is_validated_and_its_structured_content_returned(
    connect: Connect,
) -> None:
    """An array-rooted outputSchema is validated and its conforming structuredContent returned.

    2026-only: through 2025-11-25 both the schema root and structuredContent are restricted to objects.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(name="ints", input_schema={"type": "object"}, output_schema=_INTS_SCHEMA),
                Tool(name="ints_bad", input_schema={"type": "object"}, output_schema=_INTS_SCHEMA),
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name in ("ints", "ints_bad")
        values: dict[str, object] = {"ints": [1, 2, 3], "ints_bad": [1, "x"]}
        return CallToolResult(content=[TextContent(text=params.name)], structured_content=values[params.name])

    server = Server("arrays", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        await client.list_tools()
        result = await client.call_tool("ints", {})
        with pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("ints_bad", {})

    assert result.structured_content == [1, 2, 3]
    # The rejection proves validation ran for the non-object root rather than being skipped.
    assert str(exc_info.value).startswith("Invalid structured content returned by tool ints_bad")


@requirement("client:jsonschema:null-structured-content")
async def test_a_wire_null_structured_content_is_rejected_as_missing_by_the_client() -> None:
    """A wire structuredContent null is rejected as missing rather than validated against {type: 'null'}.

    Scripted over raw streams: the typed Server cannot author a wire null, and Client cannot drive raw streams.
    When the SDK gains an absent-vs-null distinction: re-pin to the resolved null result and delete the Divergence.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def scripted_server() -> None:
            with anyio.fail_after(5):
                listing = await server_read.receive()
            assert isinstance(listing, SessionMessage)
            assert isinstance(listing.message, JSONRPCRequest)
            assert listing.message.method == "tools/list"
            await server_write.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=listing.message.id,
                        # ttlMs/cacheScope/resultType are required v2026 scaffolding; the caching tests own them.
                        result={
                            "tools": [
                                {"name": "nil", "inputSchema": {"type": "object"}, "outputSchema": {"type": "null"}}
                            ],
                            "resultType": "complete",
                            "ttlMs": 0,
                            "cacheScope": "private",
                        },
                    )
                )
            )
            with anyio.fail_after(5):
                call = await server_read.receive()
            assert isinstance(call, SessionMessage)
            assert isinstance(call.message, JSONRPCRequest)
            assert call.message.method == "tools/call"
            assert call.message.params is not None
            assert call.message.params["name"] == "nil"
            await server_write.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=call.message.id,
                        # None here IS the JSON null under test -- these raw dicts are the wire.
                        result={
                            "content": [{"type": "text", "text": "null"}],
                            "resultType": "complete",
                            "structuredContent": None,
                        },
                    )
                )
            )

        # Combined async-with: a nested `async with` mis-traces its exit arcs under branch coverage on 3.11+.
        async with (
            anyio.create_task_group() as task_group,
            ClientSession(client_read, client_write, client_info=Implementation(name="cli", version="0")) as session,
        ):
            task_group.start_soon(scripted_server)
            session.adopt(
                DiscoverResult(
                    supported_versions=[LATEST_MODERN_VERSION],
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="srv", version="0"),
                )
            )
            with anyio.fail_after(5):
                listed = await session.list_tools()
            assert [(tool.name, tool.output_schema) for tool in listed.tools] == [("nil", {"type": "null"})]
            with pytest.raises(RuntimeError) as exc_info:
                with anyio.fail_after(5):
                    await session.call_tool("nil", {})
            assert str(exc_info.value) == snapshot(
                "Tool nil has an output schema but did not return structured content"
            )
