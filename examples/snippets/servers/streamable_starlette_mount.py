"""Run from the repository root:
uvicorn examples.snippets.servers.streamable_starlette_mount:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create the Echo server
echo_mcp = FastMCP(name="EchoServer")


@echo_mcp.tool()
def echo(message: str) -> str:
    """A simple echo tool"""
    return f"Echo: {message}"


# Create the Math server
math_mcp = FastMCP(name="MathServer")


@math_mcp.tool()
def add_two(n: int) -> int:
    """Tool to add two to the input"""
    return n + 2


# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(echo_mcp.session_manager.run())
        await stack.enter_async_context(math_mcp.session_manager.run())
        yield


# Create the Starlette app and mount the MCP servers
app = Starlette(
    routes=[
        Mount("/echo", echo_mcp.streamable_http_app(stateless_http=True, json_response=True)),
        Mount("/math", math_mcp.streamable_http_app(stateless_http=True, json_response=True)),
    ],
    lifespan=lifespan,
)

# Note: Clients connect to http://localhost:8000/echo/mcp and http://localhost:8000/math/mcp
# To mount at the root of each path (e.g., /echo instead of /echo/mcp):
# echo_mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)
# math_mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)
