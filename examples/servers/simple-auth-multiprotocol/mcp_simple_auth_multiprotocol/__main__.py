"""Entry point for multi-protocol MCP Resource Server."""

import sys

from mcp_simple_auth_multiprotocol.server import main

sys.exit(main())  # type: ignore[call-arg]
