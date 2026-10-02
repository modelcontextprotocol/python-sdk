import time

import anyio.from_thread

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


def index_book(title: str) -> None:
    time.sleep(1)  # slow work with nothing to await


@mcp.tool()
def rebuild_index(titles: list[str]) -> str:
    """Rebuild the search index, one book at a time."""
    for title in titles:
        anyio.from_thread.check_cancelled()
        index_book(title)
    return f"Indexed {len(titles)} books."
