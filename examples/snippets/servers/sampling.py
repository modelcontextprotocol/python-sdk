from mcp_types import SamplingMessage, TextContent

from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer(name="Sampling Example")


@mcp.tool()
async def generate_poem(topic: str, ctx: Context) -> str:
    """Generate a poem using LLM sampling."""
    prompt = f"Write a short poem about {topic}"

    result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt),
            )
        ],
        max_tokens=100,
    )

    # Without the tools param, result.content is a single content block (not a list)
    if result.content.type == "text":
        return result.content.text
    return str(result.content)
