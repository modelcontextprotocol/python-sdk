from mcp.shared._lazy_submodules import submodule_getattr as _submodule_getattr

from .caching import CacheHint
from .context import ServerRequestContext
from .lowlevel import NotificationOptions, Server
from .mcpserver import MCPServer
from .models import InitializationOptions

__all__ = ["CacheHint", "Server", "ServerRequestContext", "MCPServer", "NotificationOptions", "InitializationOptions"]

# `mcp.server.<submodule>` (stdio, session, streamable_http, auth, ...)
# resolves by attribute access even before that submodule was imported:
# the lazy `mcp` package no longer imports them all up front.
__getattr__ = _submodule_getattr(__name__)
