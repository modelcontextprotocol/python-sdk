from mcp import Client
from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.prompt(title="Recommend a book")
def recommend(genre: str) -> str:
    """Ask for a recommendation in a genre."""
    return f"Recommend one {genre} book from the catalog and say why."


async def main() -> None:
    async with Client(mcp) as client:
        listed = await client.list_prompts()
        print(listed.prompts)

        result = await client.get_prompt("recommend", {"genre": "poetry"})
        for message in result.messages:
            print(message.role, message.content)
