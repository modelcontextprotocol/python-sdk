"""Bearer-gated MCP resource server (lowlevel API) + the same minimal ``client_credentials`` AS."""

import base64
import json
import secrets
from typing import Any

import mcp_types as types
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.auth import OAuthMetadata, OAuthToken
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories._shared.auth import BASE_URL, auth_settings

from .server import DEMO_CLIENT_ID, DEMO_CLIENT_SECRET, DEMO_SCOPE


def build_app() -> Starlette:
    issued: dict[str, AccessToken] = {}

    class _Verifier:
        async def verify_token(self, token: str) -> AccessToken | None:
            return issued.get(token)

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="whoami", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "whoami"
        token = get_access_token()
        assert token is not None
        payload = {"client_id": token.client_id, "scopes": token.scopes}
        return types.CallToolResult(content=[types.TextContent(text=json.dumps(payload))], structured_content=payload)

    server = Server("oauth-client-credentials-example", on_list_tools=list_tools, on_call_tool=call_tool)

    async def as_metadata(request: Request) -> JSONResponse:
        meta = OAuthMetadata(
            issuer=AnyHttpUrl(BASE_URL),
            authorization_endpoint=AnyHttpUrl(f"{BASE_URL}/authorize"),  # unused; required
            token_endpoint=AnyHttpUrl(f"{BASE_URL}/token"),
            grant_types_supported=["client_credentials"],
            token_endpoint_auth_methods_supported=["client_secret_basic"],
            scopes_supported=[DEMO_SCOPE],
        )
        return JSONResponse(meta.model_dump(by_alias=True, mode="json", exclude_none=True))

    async def token_endpoint(request: Request) -> JSONResponse:
        form = await request.form()
        if form.get("grant_type") != "client_credentials":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        creds = base64.b64decode(request.headers.get("authorization", "").removeprefix("Basic ")).decode()
        if creds != f"{DEMO_CLIENT_ID}:{DEMO_CLIENT_SECRET}":
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        access = f"access_{secrets.token_hex(16)}"
        issued[access] = AccessToken(token=access, client_id=DEMO_CLIENT_ID, scopes=[DEMO_SCOPE], expires_at=None)
        body = OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=DEMO_SCOPE)
        return JSONResponse(body.model_dump(exclude_none=True), headers={"cache-control": "no-store"})

    return server.streamable_http_app(
        auth=auth_settings(required_scopes=[DEMO_SCOPE]),
        token_verifier=_Verifier(),
        custom_starlette_routes=[
            Route("/.well-known/oauth-authorization-server", as_metadata, methods=["GET"]),
            Route("/token", token_endpoint, methods=["POST"]),
        ],
        transport_security=NO_DNS_REBIND,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
