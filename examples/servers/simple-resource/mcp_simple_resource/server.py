import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from pydantic import FileUrl

SAMPLE_RESOURCES = {
    "greeting": "Hello! This is a sample text resource.",
    "help": "This server provides a few sample text resources for testing.",
    "about": "This is the simple-resource MCP server implementation.",
}


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server("mcp-simple-resource")

    @app.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=FileUrl(f"file:///{name}.txt"),
                name=name,
                description=f"A sample text resource named {name}",
                mimeType="text/plain",
            )
            for name in SAMPLE_RESOURCES.keys()
        ]

    @app.read_resource()
    async def read_resource(uri: FileUrl) -> str | bytes:
        name = uri.path.replace(".txt", "").lstrip("/")

        if name not in SAMPLE_RESOURCES:
            raise ValueError(f"Unknown resource: {uri}")

        return SAMPLE_RESOURCES[name]

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn

        uvicorn.run(starlette_app, host="0.0.0.0", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        anyio.run(arun)

    return 0
