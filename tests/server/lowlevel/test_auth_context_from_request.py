"""The lowlevel server applies each request's authenticated user while handling it.

Regression coverage for issue #1250 at the dispatch layer: handlers run in
the session's long-lived task, so the `auth_context_var` set by
`AuthContextMiddleware` on the HTTP request's task would otherwise still hold
the session-opening request's user. `_handle_request` re-applies the user
from the request the transport attached to the message metadata.
"""

from typing import Any
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


def make_server(observed: list[str | None]) -> Server:
    server = Server("test-server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [types.Tool(name="echo_token", description="echo", inputSchema={"type": "object"})]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        assert name == "echo_token"
        token = get_access_token()
        observed.append(token.token if token else None)
        return [types.TextContent(type="text", text=token.token if token else "no-token")]

    return server


async def dispatch(server: Server, metadata: ServerMessageMetadata | None) -> Mock:
    message = Mock(spec=RequestResponder)
    message.request_id = "req-1"
    message.request_meta = None
    message.message_metadata = metadata
    message.respond = AsyncMock()

    session = Mock(spec=ServerSession)
    session.client_params = None

    request = types.CallToolRequest(params=types.CallToolRequestParams(name="echo_token", arguments={}))
    await server._handle_request(message, request, session, {}, raise_exceptions=False)
    return message


def request_with_scope(scope: Scope) -> Request:
    return Request(scope)


@pytest.mark.anyio
async def test_handle_request_applies_the_user_from_the_request_scope() -> None:
    """A handler sees the user authenticated for its own request, and the var is reset after."""
    observed: list[str | None] = []
    server = make_server(observed)

    verified = AccessToken(token="scope" + "-token", client_id="test-client", scopes=["test"])
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [],
        "user": AuthenticatedUser(verified),
    }
    message = await dispatch(server, ServerMessageMetadata(request_context=request_with_scope(scope)))

    assert observed == ["scope-token"]
    assert auth_context_var.get() is None
    response = message.respond.call_args.args[0]
    assert isinstance(response.root, types.CallToolResult)
    content = response.root.content[0]
    assert isinstance(content, types.TextContent)
    assert content.text == "scope-token"


@pytest.mark.anyio
async def test_handle_request_without_a_user_in_scope_leaves_the_context_empty() -> None:
    """Requests whose scope carries no authenticated user run unauthenticated."""
    observed: list[str | None] = []
    server = make_server(observed)

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}
    await dispatch(server, ServerMessageMetadata(request_context=request_with_scope(scope)))

    assert observed == [None]
    assert auth_context_var.get() is None


@pytest.mark.anyio
async def test_handle_request_with_a_non_authenticated_user_in_scope_leaves_the_context_empty() -> None:
    """A scope user that is not an `AuthenticatedUser` (e.g. a plain Starlette user) is ignored."""
    observed: list[str | None] = []
    server = make_server(observed)

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [], "user": object()}
    await dispatch(server, ServerMessageMetadata(request_context=request_with_scope(scope)))

    assert observed == [None]


@pytest.mark.anyio
async def test_handle_request_with_an_attached_object_without_a_scope_leaves_the_context_empty() -> None:
    """A request context that is not a Starlette request has no scope to read a user from."""
    observed: list[str | None] = []
    server = make_server(observed)

    await dispatch(server, ServerMessageMetadata(request_context=object()))

    assert observed == [None]


@pytest.mark.anyio
async def test_handle_request_without_metadata_leaves_the_context_empty() -> None:
    """Transports that attach no request (e.g. stdio) run unauthenticated, as before."""
    observed: list[str | None] = []
    server = make_server(observed)

    await dispatch(server, None)

    assert observed == [None]
    assert auth_context_var.get() is None
