"""Transparent OAuth proxy helpers (library form).

This sub-package turns the demo-level transparent OAuth proxy into a reusable
component:

* configure_colored_logging – colourised root-logger setup identical to the
  original example.
* create_proxy_routes(provider) – returns the Starlette routes that expose the
  proxy endpoints (/authorize, /revoke …).
* build_proxy_server() – convenience helper that wires everything into a
  FastMCP instance.

The functions are re-exported here so users can simply::

    from mcp.server.auth.proxy import build_proxy_server

"""

from __future__ import annotations

# Public re-exports
from .logging import configure_colored_logging
from .routes import create_proxy_routes, fetch_upstream_metadata

__all__: list[str] = [
    "configure_colored_logging",
    "create_proxy_routes",
    "fetch_upstream_metadata",
]

# build_proxy_server intentionally *not* imported here to avoid circular
# imports with TransparentOAuthProxyProvider. Import from
# `mcp.server.auth.proxy.server` when needed:
#    from mcp.server.auth.proxy.server import build_proxy_server 