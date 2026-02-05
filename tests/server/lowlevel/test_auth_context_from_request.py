from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request
from starlette.types import Scope

import mcp.types as types
from mcp.server.auth.middleware.auth_context import auth_context_var, get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.session import RequestResponder


@pytest.mark.anyio
async def test_handle_request_sets_auth_context_from_request() -> None:
    server = Server("test-server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo_access_token",
                description="Return access token",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, object]) -> list[types.TextContent]:
        assert name == "echo_access_token"
        access_token = get_access_token()
        token = access_token.token if access_token else ""
        return [types.TextContent(type="text", text=token)]

    access_token = AccessToken(token="test-token", client_id="client", scopes=["test"])
    user = AuthenticatedUser(access_token)
    headers: list[tuple[bytes, bytes]] = []
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": headers,
        "user": user,
    }
    request = Request(scope)

    message = Mock(spec=RequestResponder)
    message.request_id = "req-1"
    message.request_meta = None
    message.message_metadata = ServerMessageMetadata(request_context=request)
    message.respond = AsyncMock()

    session = Mock(spec=ServerSession)
    session.client_params = None

    call_request = types.CallToolRequest(params=types.CallToolRequestParams(name="echo_access_token", arguments={}))

    await server._handle_request(message, call_request, session, {}, raise_exceptions=False)

    assert auth_context_var.get() is None
    assert message.respond.called
    response = message.respond.call_args.args[0]
    assert isinstance(response.root, types.CallToolResult)
    content = response.root.content[0]
    assert isinstance(content, types.TextContent)
    assert content.text == "test-token"
