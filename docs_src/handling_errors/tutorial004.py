from mcp.server import MCPServer

mcp = MCPServer("Bookshop")

CATALOG = {"Dune": "Frank Herbert", "Neuromancer": "William Gibson"}


@mcp.tool()
def get_author(title: str) -> str:
    """Look up the author of a book in the catalog."""
    return CATALOG[title]
