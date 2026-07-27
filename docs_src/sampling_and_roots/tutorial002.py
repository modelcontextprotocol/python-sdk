from typing import Annotated

from mcp_types import ListRootsResult

from mcp.server import MCPServer
from mcp.server.mcpserver import ListRoots, Resolve

mcp = MCPServer("Bookshop")


def workspace_roots() -> ListRoots:
    return ListRoots()


@mcp.tool()
async def catalog_folder(roots: Annotated[ListRootsResult, Resolve(workspace_roots)]) -> str:
    """Pick the folder the catalog export should go to."""
    if not roots.roots:
        return "No workspace folders shared."
    return str(roots.roots[0].uri)
