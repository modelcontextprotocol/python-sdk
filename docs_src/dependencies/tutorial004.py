from typing import Annotated

from mcp_types import CreateMessageResult, SamplingMessage, TextContent

from mcp.server import MCPServer
from mcp.server.mcpserver import Resolve, Sample

mcp = MCPServer("Bookshop")


def suggest_title(genre: str) -> Sample:
    prompt = f"Suggest one {genre} book title. Answer with the title only."
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
        max_tokens=50,
    )


@mcp.tool()
async def recommend_book(
    genre: str,
    suggestion: Annotated[CreateMessageResult, Resolve(suggest_title)],
) -> str:
    """Recommend a book in the given genre."""
    title = suggestion.content.text if suggestion.content.type == "text" else "the classics"
    return f"Today's {genre} pick: {title}"
