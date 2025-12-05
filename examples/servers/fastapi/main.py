"""Example showing how to mount FastMCP on a FastAPI application."""

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan that initializes the MCP session manager.

    This is necessary because FastAPI doesn't automatically trigger
    the lifespan of mounted sub-applications. We need to manually
    manage the session_manager's lifecycle.
    """
    async with mcp.session_manager.run():
        yield


# Create FastAPI app with lifespan
app = FastAPI(
    title="My API with MCP",
    description="Example FastAPI application with mounted MCP endpoint",
    version="1.0.0",
    lifespan=lifespan,
)

# Create FastMCP instance
mcp = FastMCP(
    "MCP Tools",
    debug=True,
    streamable_http_path="/",
    json_response=True,
    stateless_http=False,  # Required when deploying in production with multiple workers
)


@mcp.tool()
async def process_data(data: str) -> str:
    """Process some data and return the result

    Args:
        data: The data to process

    Returns:
        The processed data
    """
    return f"Processed: {data}"


# Get the MCP ASGI Starlette app
mcp_app = mcp.streamable_http_app()

# Mount the MCP app on FastAPI at /mcp
app.mount("/mcp", mcp_app)


# Add regular FastAPI endpoints
@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with API information"""
    return {
        "mcp_endpoint": "/mcp",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.post("/hello")
async def hello(name: str = "World") -> dict[str, str]:
    """Example FastAPI endpoint

    Args:
        name: Name to greet

    Returns:
        A greeting message
    """
    return {"message": f"Hello, {name}!"}
