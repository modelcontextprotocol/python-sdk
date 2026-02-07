"""Entry point for multi-protocol MCP Resource Server."""

import sys

from .server import main

sys.exit(main())  # type: ignore[call-arg]
