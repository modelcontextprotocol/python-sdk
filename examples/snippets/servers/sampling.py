from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ModelHint, ModelPreferences, SamplingMessage, TextContent

mcp = MCPServer(name="Sampling Example")


@mcp.tool()
async def generate_poem(topic: str, ctx: Context) -> str:
    """Generate a poem using LLM sampling."""
    prompt = f"Write a short poem about {topic}"

    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt),
            )
        ],
        max_tokens=100,
        model_preferences=ModelPreferences(
            hints=[ModelHint(name="claude-3")],
            intelligence_priority=0.8,
            speed_priority=0.2,
        ),
        include_context="thisServer",
    )

    # Since we're not passing tools param, result.content is single content
    if result.content.type == "text":
        return result.content.text
    return str(result.content)
