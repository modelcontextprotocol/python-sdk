"""Streamable HTTP defaults shared by the transport and the servers' signatures.

A leaf module with no third-party imports: `mcp.server.lowlevel` and
`mcp.server.mcpserver` use these as parameter defaults, and importing them from
the HTTP transport modules (which need starlette) would drag the HTTP stack
into every stdio server at import time. `mcp.server.streamable_http_manager`
re-exports the constant under its documented import path.
"""

from typing import Final

DEFAULT_MAX_REQUEST_BODY_SIZE: Final = 4 * 1024 * 1024
"""Default maximum Streamable HTTP request body size in bytes (4 MiB)."""
