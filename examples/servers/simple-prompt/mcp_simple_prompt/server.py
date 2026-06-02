import anyio
import click
from mcp import types
from mcp.server import Server, ServerRequestContext


def create_messages(context: str | None = None, topic: str | None = None) -> list[types.PromptMessage]:
    """Create the messages for the prompt."""
    messages: list[types.PromptMessage] = []

    # Add context if provided
    if context:
        messages.append(
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=f"Here is some relevant context: {context}"),
            )
        )

    # Add the main prompt
    prompt = "Please help me with "
    if topic:
        prompt += f"the following topic: {topic}"
    else:
        prompt += "whatever questions I may have."

    messages.append(types.PromptMessage(role="user", content=types.TextContent(type="text", text=prompt)))

    return messages


async def handle_list_prompts(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListPromptsResult:
    return types.ListPromptsResult(
        prompts=[
            types.Prompt(
                name="simple",
                title="Simple Assistant Prompt",
                description="A simple prompt that can take optional context and topic arguments",
                arguments=[
                    types.PromptArgument(
                        name="context",
                        description="Additional context to consider",
                        required=False,
                    ),
                    types.PromptArgument(
                        name="topic",
                        description="Specific topic to focus on",
                        required=False,
                    ),
                ],
            )
        ]
    )


async def handle_get_prompt(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> types.GetPromptResult:
    if params.name != "simple":
        raise ValueError(f"Unknown prompt: {params.name}")

    arguments = params.arguments or {}

    return types.GetPromptResult(
        messages=create_messages(context=arguments.get("context"), topic=arguments.get("topic")),
        description="A simple prompt with optional context and topic arguments",
    )


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
        "mcp-simple-prompt",
        on_list_prompts=handle_list_prompts,
        on_get_prompt=handle_get_prompt,
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
