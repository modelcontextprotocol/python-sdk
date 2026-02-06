"""Entry point for multi-protocol MCP Resource Server (path-only unified discovery)."""

import sys

from .server import main

sys.exit(main())  # type: ignore[call-arg]
