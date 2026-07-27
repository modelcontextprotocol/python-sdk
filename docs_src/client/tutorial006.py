from mcp_types import Completion, CompletionArgument, CompletionContext, PromptReference, ResourceTemplateReference

from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")

GENRES = ["fiction", "non-fiction", "poetry"]


@mcp.prompt()
def recommend(genre: str) -> str:
    """Ask for a recommendation in a genre."""
    return f"Recommend one {genre} book from the catalog and say why."


@mcp.completion()
async def complete_genre(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    return Completion(values=[genre for genre in GENRES if genre.startswith(argument.value)])


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.complete(
            ref=PromptReference(type="ref/prompt", name="recommend"),
            argument={"name": "genre", "value": "p"},
        )
        print(result.completion.values)
