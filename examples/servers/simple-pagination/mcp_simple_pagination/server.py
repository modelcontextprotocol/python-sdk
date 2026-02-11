"""Simple MCP server demonstrating pagination for tools, resources, and prompts.

This example shows how to use the on_* handler pattern to handle large lists
of items that need to be split across multiple pages.
"""

from typing import Any

import anyio
import click
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from starlette.requests import Request

# Sample data - in real scenarios, this might come from a database
SAMPLE_TOOLS = [
    types.Tool(
        name=f"tool_{i}",
        title=f"Tool {i}",
        description=f"This is sample tool number {i}",
        input_schema={"type": "object", "properties": {"input": {"type": "string"}}},
    )
    for i in range(1, 26)  # 25 tools total
]

SAMPLE_RESOURCES = [
    types.Resource(
        uri=f"file:///path/to/resource_{i}.txt",
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


async def handle_list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    """Paginated list_tools - returns 5 tools per page."""
    page_size = 5

    cursor = params.cursor if params is not None else None
    if cursor is None:
        start_idx = 0
    else:
        try:
            start_idx = int(cursor)
        except (ValueError, TypeError):
            return types.ListToolsResult(tools=[], next_cursor=None)

    page_tools = SAMPLE_TOOLS[start_idx : start_idx + page_size]

    next_cursor = None
    if start_idx + page_size < len(SAMPLE_TOOLS):
        next_cursor = str(start_idx + page_size)

    return types.ListToolsResult(tools=page_tools, next_cursor=next_cursor)


async def handle_list_resources(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    """Paginated list_resources - returns 10 resources per page."""
    page_size = 10

    cursor = params.cursor if params is not None else None
    if cursor is None:
        start_idx = 0
    else:
        try:
            start_idx = int(cursor)
        except (ValueError, TypeError):
            return types.ListResourcesResult(resources=[], next_cursor=None)

    page_resources = SAMPLE_RESOURCES[start_idx : start_idx + page_size]

    next_cursor = None
    if start_idx + page_size < len(SAMPLE_RESOURCES):
        next_cursor = str(start_idx + page_size)

    return types.ListResourcesResult(resources=page_resources, next_cursor=next_cursor)


async def handle_list_prompts(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListPromptsResult:
    """Paginated list_prompts - returns 7 prompts per page."""
    page_size = 7

    cursor = params.cursor if params is not None else None
    if cursor is None:
        start_idx = 0
    else:
        try:
            start_idx = int(cursor)
        except (ValueError, TypeError):
            return types.ListPromptsResult(prompts=[], next_cursor=None)

    page_prompts = SAMPLE_PROMPTS[start_idx : start_idx + page_size]

    next_cursor = None
    if start_idx + page_size < len(SAMPLE_PROMPTS):
        next_cursor = str(start_idx + page_size)

    return types.ListPromptsResult(prompts=page_prompts, next_cursor=next_cursor)


async def handle_call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle tool calls."""
    tool = next((t for t in SAMPLE_TOOLS if t.name == params.name), None)
    if not tool:
        raise ValueError(f"Unknown tool: {params.name}")

    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=f"Called tool '{params.name}' with arguments: {params.arguments}",
            )
        ]
    )


async def handle_read_resource(
    ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
) -> types.ReadResourceResult:
    """Handle read_resource requests."""
    resource = next((r for r in SAMPLE_RESOURCES if r.uri == params.uri), None)
    if not resource:
        raise ValueError(f"Unknown resource: {params.uri}")

    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(
                uri=params.uri,
                text=f"Content of {resource.name}: This is sample content for the resource.",
                mime_type="text/plain",
            )
        ]
    )


async def handle_get_prompt(
    ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams
) -> types.GetPromptResult:
    """Handle get_prompt requests."""
    prompt = next((p for p in SAMPLE_PROMPTS if p.name == params.name), None)
    if not prompt:
        raise ValueError(f"Unknown prompt: {params.name}")

    message_text = f"This is the prompt '{params.name}'"
    if params.arguments:
        message_text += f" with arguments: {params.arguments}"

    return types.GetPromptResult(
        description=prompt.description,
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=message_text),
            )
        ],
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
        "mcp-simple-pagination",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
        on_list_resources=handle_list_resources,
        on_read_resource=handle_read_resource,
        on_list_prompts=handle_list_prompts,
        on_get_prompt=handle_get_prompt,
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
