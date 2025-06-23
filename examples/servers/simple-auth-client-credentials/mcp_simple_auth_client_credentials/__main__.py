"""Main entry point for simple MCP server with Discord OAuth authentication over client credentials."""

import sys

from mcp_simple_auth_client_credentials.server import main

sys.exit(main())  # type: ignore[call-arg]
