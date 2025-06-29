"""Main entry point for the Everything Server."""

from .server import create_everything_server


def main():
    """Run the everything server."""
    mcp = create_everything_server()
    # Use FastMCP's built-in run method for better CLI integration
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()