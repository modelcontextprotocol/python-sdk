from pydantic import BaseModel, Field

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


class Book(BaseModel):
    title: str
    author: str
    year: int = Field(ge=1450, description="Year of first publication.")


@mcp.tool()
def add_book(book: Book) -> str:
    """Add a book to the catalog."""
    return f"Added {book.title!r} by {book.author} ({book.year})."
