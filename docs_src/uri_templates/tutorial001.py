from mcp.server import MCPServer

mcp = MCPServer("Bookshop")

BOOKS = {
    "978-0441172719": {"title": "Dune", "author": "Frank Herbert"},
    "978-0553293357": {"title": "Foundation", "author": "Isaac Asimov"},
}

MANUALS = {
    "printing/setup.md": "# Printer setup\n\nLoad paper, then power on.",
    "returns.md": "# Returns policy\n\nThirty days with a receipt.",
}


@mcp.resource("books://{isbn}")
def get_book(isbn: str) -> dict[str, str]:
    """A single book by ISBN."""
    return BOOKS[isbn]


@mcp.resource("orders://{order_id}")
def get_order(order_id: int) -> dict[str, object]:
    """An order by its numeric id."""
    return {"order_id": order_id, "next_order": order_id + 1, "status": "shipped"}


@mcp.resource("manuals://{+path}")
def read_manual(path: str) -> str:
    """A staff manual page. The path keeps its slashes."""
    return MANUALS[path]


@mcp.resource("reviews://{isbn}{?limit,sort}")
def list_reviews(isbn: str, limit: int = 10, sort: str = "newest") -> str:
    """Reviews of a book, optionally limited and sorted."""
    return f"{limit} {sort} reviews of {BOOKS[isbn]['title']}"


@mcp.resource("shelves://browse{/path*}")
def browse_shelf(path: list[str]) -> str:
    """A shelf in the category tree, addressed by segments."""
    return " > ".join(["catalog", *path])
