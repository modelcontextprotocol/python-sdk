from mcp.server import MCPServer

mcp = MCPServer(
    name="Demo",
    instructions=(
        "This server exposes two groups of tools: 'read_*' for fetching data "
        "and 'write_*' for persisting it. Always call a read tool before a "
        "write tool, and prefer batch_write over repeated single writes."
    ),
)


@mcp.tool()
def read_status() -> str:
    """Read the current system status."""
    return "ok"


@mcp.tool()
def write_record(data: str) -> str:
    """Persist a record."""
    return f"wrote: {data}"
