"""Entry point for multi-protocol MCP Resource Server (OAuth-fallback discovery)."""

import sys

from mcp_simple_auth_multiprotocol_oauth_fallback.server import main

sys.exit(main())  # type: ignore[call-arg]

