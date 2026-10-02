from typing import Annotated

from pydantic import Field

from mcp.server import MCPServer

mcp = MCPServer("Bookshop")


@mcp.tool()
def check_stock(
    title: str,
    region: Annotated[str, Field(json_schema_extra={"x-mcp-header": "Region"})],
) -> str:
    """Count the copies of a book in one region's warehouses."""
    return f"{title}: 3 copies in {region}."
