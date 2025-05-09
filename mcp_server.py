from mcp.server.fastmcp import FastMCP

# Create a compliant MCP server instance
mcp = FastMCP("Compliant MCP Demo Server")


# Define a simple MCP tool for demonstration
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


# Run the server using stdio transport (as recommended by MCP)
if __name__ == "__main__":
    print("Starting Compliant MCP Server...")
    mcp.run(transport="stdio")
