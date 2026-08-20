"""`dispatch_input_request` and `validate_tool_result` are public `ClientSession` API."""

import mcp_types as types
import pytest
from mcp_types import (
    CallToolResult,
    ErrorData,
    ListRootsResult,
    ListToolsResult,
    PaginatedRequestParams,
    Tool,
)

from mcp.client.client import Client
from mcp.client.session import ClientRequestContext, ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair


@pytest.mark.anyio
async def test_dispatch_input_request_routes_through_the_callback_table() -> None:
    expected = ListRootsResult(roots=[])

    async def list_roots(context: ClientRequestContext) -> ListRootsResult:
        return expected

    client_side, _server_side = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_side, list_roots_callback=list_roots)
    ctx = ClientRequestContext(session=session, request_id="r-1")
    response = await session.dispatch_input_request(ctx, types.ListRootsRequest())
    assert response is expected


@pytest.mark.anyio
async def test_dispatch_input_request_returns_error_data_on_refusal() -> None:
    """With no callback registered, refusal comes back as `ErrorData`, not a raise."""
    client_side, _server_side = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_side)
    ctx = ClientRequestContext(session=session, request_id="r-1")
    response = await session.dispatch_input_request(ctx, types.ListRootsRequest())
    assert isinstance(response, ErrorData)
    assert response.code == types.INVALID_REQUEST


def _make_server(output_schema: dict[str, object]) -> Server:
    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"}, output_schema=output_schema)])

    return Server("test-server", on_list_tools=on_list_tools)


@pytest.mark.anyio
async def test_validate_tool_result_passes_a_conforming_result() -> None:
    server = _make_server({"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
    async with Client(server) as client:
        # The session fetches the listing itself when the tool isn't cached yet.
        await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": 1}))


@pytest.mark.anyio
async def test_validate_tool_result_raises_on_schema_mismatch() -> None:
    server = _make_server({"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
    async with Client(server) as client:
        # Stable SDK prefix only: the message tail is jsonschema text that shifts with the dependency.
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool t"):
            await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": "no"}))


@pytest.mark.anyio
async def test_validate_tool_result_accepts_explicit_json_null_when_the_schema_allows_it() -> None:
    """SEP-2106: JSON null is a legal structuredContent value. A parsed result that
    includes `"structuredContent": null` must be validated against the schema, not
    rejected as a missing field. Pydantic stores both omitted and JSON null as None;
    `model_fields_set` is how the client tells them apart.
    """
    server = _make_server({"type": "null"})
    parsed = CallToolResult.model_validate({"content": [], "structuredContent": None})
    async with Client(server) as client:
        await client.session.validate_tool_result("t", parsed)


@pytest.mark.anyio
async def test_validate_tool_result_rejects_explicit_json_null_when_the_schema_does_not_allow_it() -> None:
    """An explicit JSON null that fails the advertised object schema is a schema mismatch,
    not a missing structuredContent field.
    """
    server = _make_server({"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
    parsed = CallToolResult.model_validate({"content": [], "structuredContent": None})
    async with Client(server) as client:
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool t"):
            await client.session.validate_tool_result("t", parsed)


@pytest.mark.anyio
async def test_validate_tool_result_still_rejects_omitted_structured_content() -> None:
    server = _make_server({"type": "null"})
    async with Client(server) as client:
        with pytest.raises(RuntimeError, match="Tool t has an output schema but did not return structured content"):
            await client.session.validate_tool_result("t", CallToolResult(content=[]))


@pytest.mark.anyio
async def test_validate_tool_result_validates_falsy_non_null_structured_content() -> None:
    """0 / false / "" are present JSON values and must be schema-checked, not treated as missing."""
    server = _make_server({"type": "number"})
    async with Client(server) as client:
        await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content=0))
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool t"):
            await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content=False))


@pytest.mark.anyio
async def test_validate_tool_result_raises_on_an_unusable_output_schema() -> None:
    """A schema that isn't valid JSON Schema is reported as such, on every call."""
    server = _make_server({"type": "not-a-json-schema-type"})
    async with Client(server) as client:
        result = CallToolResult(content=[], structured_content={"x": 1})
        for _ in range(2):
            # Compiling is never cached on failure, so the second call raises like the first.
            # Stable SDK prefix only: the message tail is jsonschema text that shifts with the dependency.
            with pytest.raises(RuntimeError, match="Invalid schema for tool t"):
                await client.session.validate_tool_result("t", result)


@pytest.mark.anyio
async def test_validate_tool_result_compiles_the_output_schema_once_per_tool() -> None:
    """Regression guard: compiling dominates validating, so the validator must outlive one call."""
    server = _make_server({"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
    async with Client(server) as client:
        result = CallToolResult(content=[], structured_content={"x": 1})
        await client.session.validate_tool_result("t", result)
        compiled = client.session._tool_output_validators["t"]
        await client.session.validate_tool_result("t", result)
        assert client.session._tool_output_validators["t"] is compiled


@pytest.mark.anyio
async def test_validate_tool_result_keeps_the_validator_across_a_relisting_of_the_same_schema() -> None:
    """SDK-defined: an unchanged schema on a re-listing (or a re-absorbed cache hit) keeps its
    compiled validator, so relisting between calls doesn't reintroduce the per-call compile."""
    server = _make_server({"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
    async with Client(server) as client:
        result = CallToolResult(content=[], structured_content={"x": 1})
        await client.session.validate_tool_result("t", result)
        compiled = client.session._tool_output_validators["t"]

        await client.session.list_tools()  # a second listing carrying an equal schema
        await client.session.validate_tool_result("t", result)
        assert client.session._tool_output_validators["t"] is compiled


@pytest.mark.anyio
async def test_validate_tool_result_recompiles_when_the_server_changes_the_schema() -> None:
    """A relisted tool must not be validated against the schema it used to declare."""
    schemas = [
        {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    ]

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"}, output_schema=schemas.pop(0))])

    server = Server("test-server", on_list_tools=on_list_tools)
    async with Client(server) as client:
        integer_result = CallToolResult(content=[], structured_content={"x": 1})
        await client.session.validate_tool_result("t", integer_result)

        await client.session.list_tools()
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool t"):
            await client.session.validate_tool_result("t", integer_result)
