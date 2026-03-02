"""MCP server demonstrating the sampling feature.

This server exposes tools that use sampling to request LLM completions
from the connected client. The client must provide a sampling callback
to handle these requests.
"""

import click
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.session import ServerSession
from mcp.types import SamplingMessage, TextContent

mcp = MCPServer(name="Sampling Example Server")


@mcp.tool()
async def summarize(text: str, ctx: Context[ServerSession, None]) -> str:
    """Summarize a piece of text using the client's LLM.

    This tool sends a sampling request to the connected client,
    asking its LLM to produce a concise summary of the given text.

    Args:
        text: The text to summarize.
    """
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Please provide a concise summary of the following text:\n\n{text}",
                ),
            )
        ],
        max_tokens=200,
    )

    if result.content.type == "text":
        return result.content.text
    return str(result.content)


@mcp.tool()
async def analyze_sentiment(text: str, ctx: Context[ServerSession, None]) -> str:
    """Analyze the sentiment of a piece of text using the client's LLM.

    Args:
        text: The text to analyze.
    """
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        "Analyze the sentiment of the following text. "
                        "Respond with exactly one word: positive, negative, or neutral.\n\n"
                        f"{text}"
                    ),
                ),
            )
        ],
        max_tokens=10,
        temperature=0.0,
    )

    if result.content.type == "text":
        return result.content.text
    return str(result.content)


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio"]),
    default="stdio",
    help="Transport type",
)
def main(transport: str) -> int:
    if transport == "stdio":
        mcp.run(transport="stdio")
    return 0
