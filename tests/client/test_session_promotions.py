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
async def test_validate_tool_result_reuses_cached_validator() -> None:
    """The compiled jsonschema validator is built once per tool and reused, not rebuilt on every call."""
    server = _make_server({"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
    async with Client(server) as client:
        await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": 1}))
        first = client.session._tool_output_validators["t"]  # pyright: ignore[reportPrivateUsage]

        await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": 2}))
        second = client.session._tool_output_validators["t"]  # pyright: ignore[reportPrivateUsage]

        assert first is second


@pytest.mark.anyio
async def test_validate_tool_result_rebuilds_validator_when_schema_changes() -> None:
    """A fresh `list_tools()` that reports a different output schema drops the stale cached validator."""
    schema_holder: dict[str, dict[str, object]] = {
        "t": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
    }

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[Tool(name="t", input_schema={"type": "object"}, output_schema=schema_holder["t"])]
        )

    server = Server("test-server", on_list_tools=on_list_tools)
    async with Client(server) as client:
        await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": 1}))
        stale_validator = client.session._tool_output_validators["t"]  # pyright: ignore[reportPrivateUsage]

        # The tool's output schema now requires a string instead of an integer.
        schema_holder["t"] = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        await client.session.list_tools()
        assert "t" not in client.session._tool_output_validators  # pyright: ignore[reportPrivateUsage]

        # The old value fails the new schema; a value matching the new schema passes,
        # and rebuilds (rather than reuses) the cached validator.
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool t"):
            await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": 1}))
        await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": "ok"}))

        fresh_validator = client.session._tool_output_validators["t"]  # pyright: ignore[reportPrivateUsage]
        assert fresh_validator is not stale_validator
