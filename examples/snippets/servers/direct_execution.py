"""Simplest way to run an MCP server: execute the file directly.

From `examples/snippets`: `uv run direct-execution-server` or `python servers/direct_execution.py`.
"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("My App")


@mcp.tool()
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
