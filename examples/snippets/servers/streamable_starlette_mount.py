"""Run from the repository root:
uvicorn examples.snippets.servers.streamable_starlette_mount:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.mcpserver import MCPServer

echo_mcp = MCPServer(name="EchoServer")


@echo_mcp.tool()
def echo(message: str) -> str:
    """A simple echo tool"""
    return f"Echo: {message}"


math_mcp = MCPServer(name="MathServer")


@math_mcp.tool()
def add_two(n: int) -> int:
    """Tool to add two to the input"""
    return n + 2


# A combined lifespan must run both servers' session managers
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(echo_mcp.session_manager.run())
        await stack.enter_async_context(math_mcp.session_manager.run())
        yield


app = Starlette(
    routes=[
        Mount("/echo", echo_mcp.streamable_http_app(stateless_http=True, json_response=True)),
        Mount("/math", math_mcp.streamable_http_app(stateless_http=True, json_response=True)),
    ],
    lifespan=lifespan,
)

# Clients connect to http://localhost:8000/echo/mcp and http://localhost:8000/math/mcp.
# To mount at the root of each path (/echo instead of /echo/mcp), pass
# streamable_http_path="/" to streamable_http_app().
