from typing import Any
from urllib.parse import urlparse

import anyio
import click
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from starlette.requests import Request

SAMPLE_RESOURCES = {
    "greeting": {
        "content": "Hello! This is a sample text resource.",
        "title": "Welcome Message",
    },
    "help": {
        "content": "This server provides a few sample text resources for testing.",
        "title": "Help Documentation",
    },
    "about": {
        "content": "This is the simple-resource MCP server implementation.",
        "title": "About This Server",
    },
}


async def handle_list_resources(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    return types.ListResourcesResult(
        resources=[
            types.Resource(
                uri=f"file:///{name}.txt",
                name=name,
                title=SAMPLE_RESOURCES[name]["title"],
                description=f"A sample text resource named {name}",
                mime_type="text/plain",
            )
            for name in SAMPLE_RESOURCES.keys()
        ]
    )


async def handle_read_resource(
    ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
) -> types.ReadResourceResult:
    parsed = urlparse(params.uri)
    if not parsed.path:
        raise ValueError(f"Invalid resource path: {params.uri}")
    name = parsed.path.replace(".txt", "").lstrip("/")

    if name not in SAMPLE_RESOURCES:
        raise ValueError(f"Unknown resource: {params.uri}")

    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(
                uri=params.uri,
                text=SAMPLE_RESOURCES[name]["content"],
                mime_type="text/plain",
            )
        ]
    )


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server(
        "mcp-simple-resource",
        on_list_resources=handle_list_resources,
        on_read_resource=handle_read_resource,
    )

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore[reportPrivateUsage]
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn

        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0
