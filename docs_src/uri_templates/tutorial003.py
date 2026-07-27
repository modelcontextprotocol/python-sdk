from mcp.server import MCPServer
from mcp.server.mcpserver import ResourceSecurity

mcp = MCPServer("Bookshop")


@mcp.resource(
    "imports://preview/{+source}",
    security=ResourceSecurity(exempt_params={"source"}),
)
def preview_import(source: str) -> str:
    """Preview a catalog import. `source` may be an absolute path."""
    return f"Would import from {source}"


relaxed = MCPServer(
    "Bookshop",
    resource_security=ResourceSecurity(reject_path_traversal=False),
)


@relaxed.resource("imports://preview/{+source}")
def preview_import_relaxed(source: str) -> str:
    """The server-wide flag exempts every resource on `relaxed`."""
    return f"Would import from {source}"
