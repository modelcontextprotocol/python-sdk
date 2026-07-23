"""Exported era classifier: the body-primary predicate, the built-in dual-era app, and CORS — exports `build_app()`."""

from collections.abc import Mapping
from typing import Any, Literal, cast

from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.inbound import InboundLadderRejection, InboundModernRoute, classify_inbound_request, parse_envelope
from stories._hosting import NO_DNS_REBIND, run_app_from_args

#: Response headers a browser-based MCP client must be able to read.
MCP_EXPOSED_HEADERS = ["Mcp-Session-Id", "WWW-Authenticate", "Last-Event-Id", "Mcp-Protocol-Version"]
#: Request headers a browser-based MCP client must be allowed to send.
MCP_ALLOWED_HEADERS = ["Authorization", "Content-Type", "Mcp-Protocol-Version", "Mcp-Session-Id", "Last-Event-Id"]
#: Streamable HTTP verbs: POST requests, the standalone GET stream, DELETE session end.
MCP_ALLOWED_METHODS = ["GET", "POST", "DELETE"]


def classify_era(
    body: Mapping[str, Any], headers: Mapping[str, str]
) -> Literal["modern", "legacy"] | InboundLadderRejection:
    """Tri-state era classifier built on the exported envelope primitives.

    Compose this in your own ASGI/ingress layer when the two eras need different
    backends. A body with no envelope claim (`parse_envelope` returns None) is
    2025-era traffic - `initialize` and other claim-less requests - so route it to
    the legacy backend; a body that claims the modern era is validated by the full
    ladder, and anything the ladder rejects is malformed-modern and should be refused
    (never silently downgraded to legacy).
    """
    raw_params = body.get("params")
    params = cast(Mapping[str, Any], raw_params) if isinstance(raw_params, Mapping) else None
    if body.get("method") != "initialize" and parse_envelope(params) is not None:
        verdict = classify_inbound_request(body, headers=headers)
        return "modern" if isinstance(verdict, InboundModernRoute) else verdict
    return "legacy"


def build_app() -> Starlette:
    mcp = MCPServer("legacy-routing-example")

    @mcp.tool()
    async def which_arm(ctx: Context) -> str:
        """Report which era the built-in router dispatched this request to."""
        pv = ctx.request_context.protocol_version
        return "modern" if pv in MODERN_PROTOCOL_VERSIONS else "legacy"

    # One Starlette app, one /mcp route, both eras: sessionful 2025 (initialize +
    # Mcp-Session-Id + GET stream) and stateless 2026 (per-request _meta envelope).
    app = mcp.streamable_http_app(transport_security=NO_DNS_REBIND)

    # CORS for browser-based clients. DEMO ONLY — restrict allow_origins in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=MCP_ALLOWED_METHODS,
        allow_headers=MCP_ALLOWED_HEADERS,
        expose_headers=MCP_EXPOSED_HEADERS,
    )
    return app


if __name__ == "__main__":
    run_app_from_args(build_app)
