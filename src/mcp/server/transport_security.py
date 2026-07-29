"""DNS rebinding protection settings for MCP server transports.

This module defines only the (web-framework-free) `TransportSecuritySettings`
model, so servers and applications can name and construct the settings
without loading starlette. The `TransportSecurityMiddleware` that enforces them
lives in `mcp.server._transport_security_middleware` (starlette-based) and stays
importable from here.
"""

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

if TYPE_CHECKING:
    from mcp.server._transport_security_middleware import (
        TransportSecurityMiddleware as TransportSecurityMiddleware,
    )

__all__ = ["TransportSecurityMiddleware", "TransportSecuritySettings"]


# TODO(Marcelo): We should flatten these settings. To be fair, I don't think we should even have this middleware.
class TransportSecuritySettings(BaseModel):
    """Settings for MCP transport security features.

    These settings help protect against DNS rebinding attacks by validating incoming request headers.
    """

    enable_dns_rebinding_protection: bool = True
    """Enable DNS rebinding protection (recommended for production)."""

    allowed_hosts: list[str] = Field(default_factory=list)
    """List of allowed Host header values.

    Only applies when `enable_dns_rebinding_protection` is `True`.
    """

    allowed_origins: list[str] = Field(default_factory=list)
    """List of allowed Origin header values.

    Only applies when `enable_dns_rebinding_protection` is `True`.
    """


# `TransportSecurityMiddleware` is the starlette-based enforcement of the
# settings above; resolving it lazily keeps this module (imported by every
# server, including stdio) free of the web stack. Runtime only, so the
# TYPE_CHECKING import above is what types the name.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(
        __name__,
        globals(),
        exports={
            "TransportSecurityMiddleware": (
                "mcp.server._transport_security_middleware",
                "TransportSecurityMiddleware",
            )
        },
    )
