import anyio
import click
import httpx2
import mcp.types as types
from mcp.server import Server, ServerRequestContext


async def fetch_website(
    url: str,
) -> list[types.ContentBlock]:
    headers = {"User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"}
    timeout = httpx2.Timeout(30, read=300)
    async with httpx2.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
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
