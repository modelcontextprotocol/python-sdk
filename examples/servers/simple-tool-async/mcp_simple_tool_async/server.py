import anyio
import click
import mcp.types as types
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.shared._httpx_utils import create_mcp_http_client

mcp = FastMCP("mcp-website-fetcher")


@mcp.tool(invocation_modes=["async"])
async def fetch_website(
    url: str,
) -> list[types.ContentBlock]:
    headers = {"User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"}
    async with create_mcp_http_client(headers=headers) as client:
        await anyio.sleep(5)
        response = await client.get(url)
        response.raise_for_status()
        return [types.TextContent(type="text", text=response.text)]


@click.command()
@click.option("--port", default=8000, help="Port to listen on for HTTP")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str):
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        app = mcp.streamable_http_app()
        server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error"))
        print(f"Starting {transport} server on port {port}")
        server.run()
    else:
        raise ValueError(f"Invalid transport for test server: {transport}")
