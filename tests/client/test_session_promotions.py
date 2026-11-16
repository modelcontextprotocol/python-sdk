"""`dispatch_input_request` and the deprecated `validate_tool_result` are public `ClientSession` API."""

import mcp_types as types
import pytest
from mcp_types import CallToolResult, ErrorData, ListRootsResult

from mcp import MCPDeprecationWarning
from mcp.client.session import ClientRequestContext, ClientSession
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


@pytest.mark.anyio
async def test_validate_tool_result_is_a_deprecated_no_op() -> None:
    """SDK-defined: the client no longer checks a result against the server's output schema."""
    client_side, _server_side = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_side)
    with pytest.warns(MCPDeprecationWarning, match="no longer validates tool results"):
        await session.validate_tool_result(  # pyright: ignore[reportDeprecated]
            "t", CallToolResult(content=[], structured_content={"x": "no"})
        )
