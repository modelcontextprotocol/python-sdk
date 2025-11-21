from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import SamplingMessage, TextContent

mcp = FastMCP(name="Sampling Example")


@mcp.tool()
async def generate_poem(topic: str, ctx: Context[ServerSession, None]) -> str:
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
    )

    content = result.content[0] if isinstance(result.content, list) else result.content
    if content.type == "text":
        return content.text
    return str(content)
