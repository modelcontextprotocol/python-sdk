from mcp.server.fastmcp import FastMCP

# Create FastMCP server
mcp = FastMCP("StatelessTest")


# Register a simple echo tool
@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back to the client."""
    return f"Echo: {message}"


if __name__ == "__main__":
    # Run in STDIO mode
    mcp.run()
