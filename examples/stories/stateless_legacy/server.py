"""The one-liner HTTP deploy: one stateless ASGI app serves both protocol eras, so it exports `build_app()`."""

from starlette.applications import Starlette

from mcp.server.mcpserver import MCPServer
from stories._hosting import NO_DNS_REBIND, run_app_from_args


def build_app() -> Starlette:
    mcp = MCPServer("stateless-legacy-example")

    @mcp.tool(description="A simple greeting tool.")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    # stateless_http=True: no Mcp-Session-Id, fresh transport per POST — horizontally
    # scalable. The same app also answers 2026-era envelope requests with no extra config.
    return mcp.streamable_http_app(stateless_http=True, transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
