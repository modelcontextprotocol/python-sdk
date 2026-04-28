import anyio
import click
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.shared._httpx_utils import create_mcp_http_client


async def fetch_website(
    url: str,
) -> list[types.ContentBlock]:
    headers = {"User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"}
    async with create_mcp_http_client(headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return [types.TextContent(type="text", text=response.text)]


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="fetch",
                title="Website Fetcher",
                description="Fetches a website and returns its content",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to fetch",
                        }
                    },
                },
            )
        ]
    )


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name != "fetch":
        raise ValueError(f"Unknown tool: {params.name}")
    arguments = params.arguments or {}
    if "url" not in arguments:
        raise ValueError("Missing required argument 'url'")
    content = await fetch_website(arguments["url"])
    return types.CallToolResult(content=content)


@click.command()
@click.option("--port", default=8000, help="Port to listen on for HTTP")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server(
        "mcp-website-fetcher",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )

    if transport == "streamable-http":
        import uvicorn

        uvicorn.run(app.streamable_http_app(), host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0
