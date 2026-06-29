from pathlib import Path

from mcp.server import MCPServer
from mcp.shared.path_security import safe_join

mcp = MCPServer("Bookshop")

DOCS_ROOT = Path("./manuals")


@mcp.resource("manuals://{+path}")
def read_manual(path: str) -> str:
    """A staff manual page, served from a directory on disk."""
    return safe_join(DOCS_ROOT, path).read_text()
