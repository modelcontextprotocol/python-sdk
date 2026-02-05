"""Entry point for multi-protocol MCP Resource Server (path-only unified discovery)."""

import sys

from mcp_simple_auth_multiprotocol_path_only.server import main

sys.exit(main())  # type: ignore[call-arg]

