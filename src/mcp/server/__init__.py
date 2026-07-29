from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

from .caching import CacheHint
from .context import ServerRequestContext
from .lowlevel import NotificationOptions, Server
from .mcpserver import MCPServer
from .models import InitializationOptions

if TYPE_CHECKING:
    # Submodules named by qualified annotations elsewhere in the SDK (e.g.
    # `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`); the
    # mirror lets type checkers follow the chain the runtime `__getattr__`
    # resolves. Add to it when spelling a new qualified annotation.
    from . import auth as auth
    from . import streamable_http_manager as streamable_http_manager

__all__ = ["CacheHint", "Server", "ServerRequestContext", "MCPServer", "NotificationOptions", "InitializationOptions"]

# `mcp.server.<submodule>` (stdio, session, streamable_http, auth, ...)
# resolves by attribute access even before that submodule was imported:
# the lazy `mcp` package no longer imports them all up front. Runtime only,
# so a type checker still flags a misspelled `mcp.server.<name>`.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals())
