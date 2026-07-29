"""Minimal MCP server that exercises every advisory field of sampling/createMessage.

The goal of this example is NOT to be a useful tool — it is to give the
companion client (examples/clients/simple-sampling-client) a server that
populates every field the MCP spec defines for sampling, so the sampling
callback can be demonstrated end-to-end.
"""

import anyio
import click
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="write_story",
                title="Write a short story",
                description="Delegates story writing to the client's LLM via sampling.",
                input_schema={
                    "type": "object",
                    "required": ["topic"],
                    "properties": {
                        "topic": {"type": "string", "description": "Subject of the story"},
                    },
                },
            )
        ]
    )


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name != "write_story":
        raise ValueError(f"Unknown tool: {params.name}")
    topic = (params.arguments or {}).get("topic")
    if not isinstance(topic, str) or not topic:
        raise ValueError("Missing required argument 'topic'")

    # We deliberately populate every advisory field so the client's
    # sampling callback has something to interpret. A real server would
    # only set the fields it actually cares about.
    result = await ctx.session.create_message(
        messages=[
            types.SamplingMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=f"Write a 3-sentence story about {topic}.",
                ),
            )
        ],
        max_tokens=200,
        system_prompt="You are a concise storyteller. Use vivid language.",
        # Hints are ordered: the client SHOULD try the first one first and
        # fall back. We list a cheap-fast model followed by a more capable
        # one; the numeric priorities below explain why.
        model_preferences=types.ModelPreferences(
            hints=[types.ModelHint(name="llama-3.1-8b"), types.ModelHint(name="llama-3.3-70b")],
            cost_priority=0.3,
            speed_priority=0.7,
            intelligence_priority=0.4,
        ),
        temperature=0.8,
        stop_sequences=["THE END"],
        # includeContext is left at "none" here because a self-contained
        # demo has no other server context to share. Flip to "thisServer"
        # to see the client log the request.
        include_context="none",
        metadata={"example": "simple-sampling"},
    )

    text = result.content.text if isinstance(result.content, types.TextContent) else "(non-text response)"
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"Model: {result.model}\n\n{text}")],
    )


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    show_default=True,
    help="Transport type. The companion client uses stdio.",
)
@click.option("--port", default=8000, show_default=True, help="Port for streamable-http transport")
def main(transport: str, port: int) -> int:
    app = Server(
        "mcp-simple-sampling",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )

    if transport == "streamable-http":
        import uvicorn

        uvicorn.run(app.streamable_http_app(), host="127.0.0.1", port=port)
        return 0

    async def arun() -> None:
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    anyio.run(arun)
    return 0
