from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.shared.path_security import safe_join

mcp = MCPServer("Bookshop")

DOCS_ROOT = Path("./manuals")


@mcp.resource("manuals://{+path}")
def read_manual(path: str) -> str:
    """A staff manual page, served from a directory on disk."""
    file = safe_join(DOCS_ROOT, path)
    if not file.is_file():
        raise ResourceNotFoundError(f"No manual at {path!r}.")
    return file.read_text(encoding="utf-8")
