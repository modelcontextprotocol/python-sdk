"""Bearer-gated resource server + a minimal in-process ``client_credentials`` AS, one app; exports ``build_app()``."""

import base64
import secrets

from pydantic import AnyHttpUrl, BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthMetadata, OAuthToken
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories._shared.auth import BASE_URL, MCP_URL, auth_settings

# DEMO ONLY — never hard-code real credentials.
DEMO_CLIENT_ID = "demo-m2m-client"
DEMO_CLIENT_SECRET = "demo-m2m-secret"
DEMO_SCOPE = "mcp:tools"


class Whoami(BaseModel):
    client_id: str
    scopes: list[str]


def build_app() -> Starlette:
    issued: dict[str, AccessToken] = {}

    class _Verifier:
        async def verify_token(self, token: str) -> AccessToken | None:
            return issued.get(token)

    mcp = MCPServer(
        "oauth-client-credentials-example",
        token_verifier=_Verifier(),
        auth=auth_settings(required_scopes=[DEMO_SCOPE]),
    )

    @mcp.tool(description="Return the authenticated client_id and granted scopes.")
    def whoami() -> Whoami:
        token = get_access_token()
        assert token is not None
        return Whoami(client_id=token.client_id, scopes=token.scopes)

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
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

    @mcp.custom_route("/token", methods=["POST"])
    async def token_endpoint(request: Request) -> JSONResponse:
        form = await request.form()
        if form.get("grant_type") != "client_credentials":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        creds = base64.b64decode(request.headers.get("authorization", "").removeprefix("Basic ")).decode()
        if creds != f"{DEMO_CLIENT_ID}:{DEMO_CLIENT_SECRET}":
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        # RFC 8707 §2.2: this AS protects exactly one resource. Anything else (or a missing
        # indicator) is answered with `invalid_target`, and the issued token is audience-bound
        # to that one resource so the bearer gate accepts it. Never mint whatever audience the
        # client names: a multi-resource AS that does so hands out tokens for resources the
        # client was never granted.
        if form.get("resource") != MCP_URL:
            return JSONResponse({"error": "invalid_target"}, status_code=400)
        access = f"access_{secrets.token_hex(16)}"
        issued[access] = AccessToken(
            token=access, client_id=DEMO_CLIENT_ID, scopes=[DEMO_SCOPE], expires_at=None, resource=MCP_URL
        )
        body = OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, scope=DEMO_SCOPE)
        return JSONResponse(body.model_dump(exclude_none=True), headers={"cache-control": "no-store"})

    return mcp.streamable_http_app(transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
