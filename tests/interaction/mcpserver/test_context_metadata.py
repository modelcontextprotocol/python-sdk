"""Context transport metadata exposed to MCPServer tools."""

import pytest
from starlette.requests import Request

from mcp.server.auth.middleware.auth_context import auth_context_var, get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import TextContent
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:context:transport-metadata")
async def test_context_exposes_transport_metadata_to_a_tool(connect: Connect) -> None:
    """A tool can read transport/session/auth metadata from its injected Context.

    The in-memory leg has no transport session id; HTTP/SSE legs expose the real HTTP request object
    and headers. The handler installs an auth token to prove the Context property matches the shared
    auth helper inside the same request scope.
    """
    mcp = MCPServer("metadata")

    @mcp.tool()
    async def inspect_context(ctx: Context) -> str:
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
        header_value = ctx.headers.get("mcp-protocol-version", "none") if ctx.headers is not None else "none"
        has_headers = ctx.headers is not None
        return "|".join(
            [
                ctx.transport.kind,
                ctx.session_id or "none",
                request_kind,
                request_path,
                header_value,
                str(has_headers),
                str(token_matches_helper),
                exposed_token.client_id if exposed_token is not None else "none",
            ]
        )

    async with connect(mcp) as client:
        result = await client.call_tool("inspect_context", {})

    assert isinstance(result.content[0], TextContent)
    text = result.content[0].text
    (
        transport_kind,
        session_id,
        request_kind,
        request_path,
        header_value,
        has_headers,
        token_matches_helper,
        token_client_id,
    ) = text.split("|")
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
        assert header_value == "none"
    assert token_matches_helper == "True"
    assert token_client_id == "client-1"
