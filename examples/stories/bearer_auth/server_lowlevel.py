"""Resource-server-only bearer auth (lowlevel API): same gate, hand-built `CallToolResult`."""

from typing import Any

import mcp_types as types
from pydantic import AnyHttpUrl
from starlette.applications import Starlette

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import NO_DNS_REBIND, run_app_from_args

from .server import ISSUER, REQUIRED_SCOPE, RESOURCE_URL, StaticTokenVerifier


def build_app() -> Starlette:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="whoami",
                    description="Return the authenticated principal.",
                    input_schema={"type": "object"},
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "whoami"
        token = get_access_token()
        assert token is not None  # the bearer gate guarantees this on the HTTP path
        payload = {"subject": token.subject or "", "client_id": token.client_id, "scopes": token.scopes}
        return types.CallToolResult(
            content=[types.TextContent(text=f"{token.subject} via {token.client_id}")],
            structured_content=payload,
        )

    server = Server("bearer-auth-example", on_list_tools=list_tools, on_call_tool=call_tool)
    # lowlevel.Server takes auth at app-build time, not in the constructor (cf. MCPServer).
    return server.streamable_http_app(
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(ISSUER),
            resource_server_url=AnyHttpUrl(RESOURCE_URL),
            required_scopes=[REQUIRED_SCOPE],
        ),
        token_verifier=StaticTokenVerifier(),
        transport_security=NO_DNS_REBIND,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
