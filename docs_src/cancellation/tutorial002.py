import time

import anyio.from_thread

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")

offline: set[str] = set()


def index_book(title: str) -> None:
    time.sleep(1)  # slow work with nothing to await


@mcp.tool()
def rebuild_index(titles: list[str]) -> str:
    """Take search offline and rebuild its index, one book at a time."""
    offline.add("search")
    try:
        for title in titles:
            anyio.from_thread.check_cancelled()
            index_book(title)
        return f"Indexed {len(titles)} books."
    finally:
        offline.discard("search")
