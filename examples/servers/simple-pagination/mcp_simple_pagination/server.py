"""
Simple MCP server demonstrating pagination for tools, resources, and prompts.

This example shows how to use the paginated decorators to handle large lists
of items that need to be split across multiple pages.
"""

from typing import Any

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from pydantic import AnyUrl
from starlette.requests import Request

# Sample data - in real scenarios, this might come from a database
SAMPLE_TOOLS = [
    types.Tool(
        name=f"tool_{i}",
        title=f"Tool {i}",
        description=f"This is sample tool number {i}",
        inputSchema={"type": "object", "properties": {"input": {"type": "string"}}},
    )
    for i in range(1, 26)  # 25 tools total
]

SAMPLE_RESOURCES = [
    types.Resource(
        uri=AnyUrl(f"file:///path/to/resource_{i}.txt"),
        name=f"resource_{i}",
        description=f"This is sample resource number {i}",
    )
    for i in range(1, 31)  # 30 resources total
]

SAMPLE_PROMPTS = [
    types.Prompt(
        name=f"prompt_{i}",
        description=f"This is sample prompt number {i}",
        arguments=[
            types.PromptArgument(name="arg1", description="First argument", required=True),
        ],
    )
    for i in range(1, 21)  # 20 prompts total
]


@click.command()
@click.option("--port", default=8000, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server("mcp-simple-pagination")

    # Paginated list_tools - returns 5 tools per page
    @app.list_tools()
    async def list_tools_paginated(request: types.ListToolsRequest) -> types.ListToolsResult:
        page_size = 5

        cursor = request.params.cursor if request.params is not None else None
        if cursor is None:
            # First page
            start_idx = 0
        else:
            # Parse cursor to get the start index
            try:
                start_idx = int(cursor)
            except (ValueError, TypeError):
                # Invalid cursor, return empty
                return types.ListToolsResult(tools=[], nextCursor=None)

        # Get the page of tools
        page_tools = SAMPLE_TOOLS[start_idx : start_idx + page_size]

        # Determine if there are more pages
        next_cursor = None
        if start_idx + page_size < len(SAMPLE_TOOLS):
            next_cursor = str(start_idx + page_size)

        return types.ListToolsResult(tools=page_tools, nextCursor=next_cursor)

    # Paginated list_resources - returns 10 resources per page
    @app.list_resources()
    async def list_resources_paginated(
        request: types.ListResourcesRequest,
    ) -> types.ListResourcesResult:
        page_size = 10

        cursor = request.params.cursor if request.params is not None else None
        if cursor is None:
            # First page
            start_idx = 0
        else:
            # Parse cursor to get the start index
            try:
                start_idx = int(cursor)
            except (ValueError, TypeError):
                # Invalid cursor, return empty
                return types.ListResourcesResult(resources=[], nextCursor=None)

        # Get the page of resources
        page_resources = SAMPLE_RESOURCES[start_idx : start_idx + page_size]

        # Determine if there are more pages
        next_cursor = None
        if start_idx + page_size < len(SAMPLE_RESOURCES):
            next_cursor = str(start_idx + page_size)

        return types.ListResourcesResult(resources=page_resources, nextCursor=next_cursor)

    # Paginated list_prompts - returns 7 prompts per page
    @app.list_prompts()
    async def list_prompts_paginated(
        request: types.ListPromptsRequest,
    ) -> types.ListPromptsResult:
        page_size = 7

        cursor = request.params.cursor if request.params is not None else None
        if cursor is None:
            # First page
            start_idx = 0
        else:
            # Parse cursor to get the start index
            try:
                start_idx = int(cursor)
            except (ValueError, TypeError):
                # Invalid cursor, return empty
                return types.ListPromptsResult(prompts=[], nextCursor=None)

        # Get the page of prompts
        page_prompts = SAMPLE_PROMPTS[start_idx : start_idx + page_size]

        # Determine if there are more pages
        next_cursor = None
        if start_idx + page_size < len(SAMPLE_PROMPTS):
            next_cursor = str(start_idx + page_size)

        return types.ListPromptsResult(prompts=page_prompts, nextCursor=next_cursor)

    # Implement call_tool handler
    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        # Find the tool in our sample data
        tool = next((t for t in SAMPLE_TOOLS if t.name == name), None)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        # Simple mock response
        return [
            types.TextContent(
                type="text",
                text=f"Called tool '{name}' with arguments: {arguments}",
            )
        ]

    # Implement read_resource handler
    @app.read_resource()
    async def read_resource(uri: AnyUrl) -> str:
        # Find the resource in our sample data
        resource = next((r for r in SAMPLE_RESOURCES if r.uri == uri), None)
        if not resource:
            raise ValueError(f"Unknown resource: {uri}")

        # Return a simple string - the decorator will convert it to TextResourceContents
        return f"Content of {resource.name}: This is sample content for the resource."

    # Implement get_prompt handler
    @app.get_prompt()
    async def get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
        # Find the prompt in our sample data
        prompt = next((p for p in SAMPLE_PROMPTS if p.name == name), None)
        if not prompt:
            raise ValueError(f"Unknown prompt: {name}")

        # Simple mock response
        message_text = f"This is the prompt '{name}'"
        if arguments:
            message_text += f" with arguments: {arguments}"

        return types.GetPromptResult(
            description=prompt.description,
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=message_text),
                )
            ],
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
