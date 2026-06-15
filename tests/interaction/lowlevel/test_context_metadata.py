"""Context transport metadata exposed to low-level server handlers."""

import pytest
from starlette.requests import Request

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.auth.middleware.auth_context import auth_context_var, get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.types import CallToolResult, TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("lowlevel:context:transport-metadata")
async def test_lowlevel_context_exposes_transport_metadata(connect: Connect) -> None:
    """A low-level handler can read transport/session/auth metadata from context."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="inspect_context", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "inspect_context"
        access_token = AccessToken(token="secret", client_id="client-1", scopes=["tools"])
        token = auth_context_var.set(AuthenticatedUser(access_token))
        try:
            exposed_token = ctx.access_token
            token_matches_helper = exposed_token == get_access_token()
        finally:
            auth_context_var.reset(token)
        request = ctx.request
        request_kind = type(request).__name__ if request is not None else "none"
        request_path = str(request.url.path) if isinstance(request, Request) else "none"
        has_headers = ctx.headers is not None
        text = "|".join(
            [
                ctx.transport.kind,
                ctx.session_id or "none",
                request_kind,
                request_path,
                str(has_headers),
                str(token_matches_helper),
                exposed_token.client_id if exposed_token is not None else "none",
            ]
        )
        return CallToolResult(content=[TextContent(text=text)])

    server = Server("metadata", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("inspect_context", {})

    assert isinstance(result.content[0], TextContent)
    text = result.content[0].text
    transport_kind, session_id, request_kind, request_path, has_headers, token_matches_helper, token_client_id = (
        text.split("|")
    )
    assert request_kind in {"Request", "none"}
    if request_kind == "Request":
        assert transport_kind == "sse" if request_path.startswith("/messages/") else "streamable-http"
        assert session_id != "none"
        assert has_headers == "True"
    else:
        assert transport_kind == "jsonrpc"
        assert session_id == "none"
        assert request_path == "none"
        assert has_headers == "False"
    assert token_matches_helper == "True"
    assert token_client_id == "client-1"
