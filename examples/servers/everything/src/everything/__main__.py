"""Main entry point for the Everything Server."""

from .server import create_everything_server


def main():
    """Run the everything server."""
    mcp = create_everything_server()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
