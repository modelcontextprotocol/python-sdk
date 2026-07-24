"""SEP-990 authorization server + bearer-gated MCP server (lowlevel API); same app shape."""

import json
from typing import Any

import mcp_types as types
from starlette.applications import Starlette

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories._shared.auth import auth_settings

from .server import DEMO_SCOPE, IdentityAssertionAuthorizationServer

WHOAMI_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "client_id": {"type": "string"},
        "scopes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "client_id", "scopes"],
}


def build_app() -> Starlette:
    provider = IdentityAssertionAuthorizationServer()

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="whoami",
                    description="Return the end user the ID-JAG named, plus the authenticated client and scopes.",
                    input_schema={"type": "object"},
                    output_schema=WHOAMI_OUTPUT_SCHEMA,
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "whoami"
        token = get_access_token()
        assert token is not None
        assert token.subject is not None
        payload = {"subject": token.subject, "client_id": token.client_id, "scopes": token.scopes}
        return types.CallToolResult(content=[types.TextContent(text=json.dumps(payload))], structured_content=payload)

    server = Server("identity-assertion-example", on_list_tools=list_tools, on_call_tool=call_tool)
    # Unlike MCPServer (auth on the constructor), lowlevel.Server takes auth at app-build time.
    return server.streamable_http_app(
        auth=auth_settings(required_scopes=[DEMO_SCOPE], identity_assertion_enabled=True),
        token_verifier=ProviderTokenVerifier(provider),
        auth_server_provider=provider,
        transport_security=NO_DNS_REBIND,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
