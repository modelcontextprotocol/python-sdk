"""Entry point for multi-protocol MCP Resource Server (root-only unified discovery)."""

import sys

from mcp_simple_auth_multiprotocol_root_only.server import main

sys.exit(main())  # type: ignore[call-arg]

