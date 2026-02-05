"""Entry point for multi-protocol MCP Resource Server (PRM-only discovery)."""

import sys

from mcp_simple_auth_multiprotocol_prm_only.server import main

sys.exit(main())  # type: ignore[call-arg]

