"""Entry point for multi-protocol MCP Resource Server (OAuth-fallback discovery)."""

import sys

from .server import main

sys.exit(main())  # type: ignore[call-arg]
