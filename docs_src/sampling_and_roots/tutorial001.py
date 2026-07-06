from typing import Annotated

from mcp_types import CreateMessageResult, SamplingMessage, TextContent

from mcp.server import MCPServer
from mcp.server.mcpserver import Resolve, Sample

mcp = MCPServer("Bookshop")


def draft_blurb(title: str) -> Sample:
    prompt = f"Write a one-sentence blurb for the book {title!r}."
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
        max_tokens=60,
    )


@mcp.tool()
async def blurb(title: str, draft: Annotated[CreateMessageResult, Resolve(draft_blurb)]) -> str:
    """Draft a blurb for a book."""
    return draft.content.text if draft.content.type == "text" else "No blurb."
