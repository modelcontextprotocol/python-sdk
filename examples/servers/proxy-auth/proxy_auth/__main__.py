"""Main entry point for Combo Proxy OAuth Resource+Auth MCP server."""

import sys

from .combo_server import main

sys.exit(main())  # type: ignore[call-arg]
