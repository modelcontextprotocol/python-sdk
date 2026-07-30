"""MCP OAuth server authorization components."""

from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

if TYPE_CHECKING:
    # Submodules named by qualified annotations elsewhere in the SDK
    # (`mcp.server.auth.provider.TokenVerifier`, ...): mirrored so type
    # checkers follow the chain the runtime `__getattr__` resolves.
    from . import provider as provider
    from . import settings as settings

# `mcp.server.auth.<submodule>` (settings, provider, routes, ...) resolves by
# attribute access without importing the auth stack up front, so qualified
# annotations such as `mcp.server.auth.provider.TokenVerifier` evaluate on
# demand in `typing.get_type_hints`. Runtime only, so a type checker still
# flags a misspelled `mcp.server.auth.<name>`.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals())
