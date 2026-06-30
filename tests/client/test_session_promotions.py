"""`dispatch_input_request` and `validate_tool_result` are public `ClientSession` API."""

import re
from pathlib import Path

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
    """The `ErrorData` arm is the refusal path: with no callback registered, the
    default callback declines and the caller receives the error, not a raise."""
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
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool t"):
            await client.session.validate_tool_result("t", CallToolResult(content=[], structured_content={"x": "no"}))


def _spell_private(name: str) -> str:
    return f"_{name}"


def test_no_private_spelling_references_remain() -> None:
    """The promotions are renames, not aliases — the old private names are gone from `src/`."""
    pattern = re.compile(f"{_spell_private('dispatch_input_request')}|{_spell_private('validate_tool_result')}")
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = [
        (path.name, match) for path in sorted(src.rglob("*.py")) for match in pattern.findall(path.read_text())
    ]
    assert not offenders
