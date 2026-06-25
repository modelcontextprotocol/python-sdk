"""Sampling primitive: a tool asks the client's LLM for a completion mid-call."""

from mcp_types import SamplingMessage, TextContent

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("sampling-example")

    @mcp.tool(description="Summarize text by asking the host's LLM via sampling/createMessage.")
    async def summarize(text: str, ctx: Context) -> str:
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[SamplingMessage(role="user", content=TextContent(text=f"Summarize in one sentence:\n\n{text}"))],
            max_tokens=200,
        )
        assert isinstance(result.content, TextContent)
        return result.content.text

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
