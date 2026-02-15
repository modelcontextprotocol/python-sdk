"""Simple MCP server demonstrating pagination for tools, resources, and prompts.

This example shows how to implement pagination with the low-level server API
to handle large lists of items that need to be split across multiple pages.
"""

from typing import TypeVar

import anyio
import click
from mcp import types
from mcp.server import Server, ServerRequestContext
from starlette.requests import Request

T = TypeVar("T")

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


def _paginate(cursor: str | None, items: list[T], page_size: int) -> tuple[list[T], str | None]:
    """Helper to paginate a list of items given a cursor."""
    if cursor is not None:
        try:
            start_idx = int(cursor)
        except (ValueError, TypeError):
            return [], None
    else:
        start_idx = 0

    page = items[start_idx : start_idx + page_size]
    next_cursor = str(start_idx + page_size) if start_idx + page_size < len(items) else None
    return page, next_cursor


# Paginated list_tools - returns 5 tools per page
async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    cursor = params.cursor if params is not None else None
    page, next_cursor = _paginate(cursor, SAMPLE_TOOLS, page_size=5)
    return types.ListToolsResult(tools=page, next_cursor=next_cursor)


# Paginated list_resources - returns 10 resources per page
async def handle_list_resources(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    cursor = params.cursor if params is not None else None
    page, next_cursor = _paginate(cursor, SAMPLE_RESOURCES, page_size=10)
    return types.ListResourcesResult(resources=page, next_cursor=next_cursor)


# Paginated list_prompts - returns 7 prompts per page
async def handle_list_prompts(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListPromptsResult:
    cursor = params.cursor if params is not None else None
    page, next_cursor = _paginate(cursor, SAMPLE_PROMPTS, page_size=7)
    return types.ListPromptsResult(prompts=page, next_cursor=next_cursor)


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    # Find the tool in our sample data
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
    ctx: ServerRequestContext, params: types.ReadResourceRequestParams
) -> types.ReadResourceResult:
    resource = next((r for r in SAMPLE_RESOURCES if r.uri == str(params.uri)), None)
    if not resource:
        raise ValueError(f"Unknown resource: {params.uri}")

    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(
                uri=str(params.uri),
                text=f"Content of {resource.name}: This is sample content for the resource.",
                mime_type="text/plain",
            )
        ]
    )


async def handle_get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> types.GetPromptResult:
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
        on_list_resources=handle_list_resources,
        on_list_prompts=handle_list_prompts,
        on_call_tool=handle_call_tool,
        on_read_resource=handle_read_resource,
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
