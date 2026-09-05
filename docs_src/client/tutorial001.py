from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Completion, CompletionArgument, CompletionContext, PromptReference, ResourceTemplateReference

mcp = MCPServer("Bookshop", instructions="Search the catalog before recommending a book.")

GENRES = ["fiction", "non-fiction", "poetry"]


class Book(BaseModel):
    title: str
    author: str
    year: int


@mcp.tool(title="Search the catalog")
def search_books(query: str, limit: int = 10) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r} (showing up to {limit})."


@mcp.tool()
def lookup_book(title: str) -> Book:
    """Look up a book by its exact title."""
    if title != "Dune":
        raise ToolError(f"No book titled {title!r} in the catalog.")
    return Book(title="Dune", author="Frank Herbert", year=1965)


@mcp.resource("catalog://genres")
def genres() -> list[str]:
    """The genres the catalog is organised by."""
    return GENRES


@mcp.resource("catalog://genres/{genre}")
def books_in_genre(genre: str) -> str:
    """Every title we stock in one genre."""
    return f"3 books filed under {genre}."


@mcp.prompt(title="Recommend a book")
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
