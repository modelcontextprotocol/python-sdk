"""DNS rebinding protection for MCP server transports."""

import logging

from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# TODO(Marcelo): We should flatten these settings. To be fair, I don't think we should even have this middleware.
class TransportSecuritySettings(BaseModel):
    """Settings for protecting MCP transports against DNS rebinding via request header validation."""

    enable_dns_rebinding_protection: bool = True
    """Enable DNS rebinding protection (recommended for production)."""

    allowed_hosts: list[str] = Field(default_factory=list)
    """Allowed Host header values; only applies when `enable_dns_rebinding_protection` is `True`."""

    allowed_origins: list[str] = Field(default_factory=list)
    """Allowed Origin header values; only applies when `enable_dns_rebinding_protection` is `True`."""


# TODO(Marcelo): This should be a proper ASGI middleware. I'm sad to see this.
class TransportSecurityMiddleware:
    """Middleware to enforce DNS rebinding protection for MCP transport endpoints."""

    def __init__(self, settings: TransportSecuritySettings | None = None):
        # Default to disabled for backwards compatibility
        self.settings = settings or TransportSecuritySettings(enable_dns_rebinding_protection=False)

    def _validate_host(self, host: str | None) -> bool:
        if not host:
            logger.warning("Missing Host header in request")
            return False

        if host in self.settings.allowed_hosts:
            return True

        # A "host:*" pattern allows any port on that host
        for allowed in self.settings.allowed_hosts:
            if allowed.endswith(":*"):
                base_host = allowed[:-2]
                if host.startswith(base_host + ":"):
                    return True

        logger.warning(f"Invalid Host header: {host}")
        return False

    def _validate_origin(self, origin: str | None) -> bool:
        # Origin can be absent for same-origin requests
        if not origin:
            return True

        if origin in self.settings.allowed_origins:
            return True

        # An "origin:*" pattern allows any port on that origin
        for allowed in self.settings.allowed_origins:
            if allowed.endswith(":*"):
                base_origin = allowed[:-2]
                if origin.startswith(base_origin + ":"):
                    return True

        logger.warning(f"Invalid Origin header: {origin}")
        return False

    def _validate_content_type(self, content_type: str | None) -> bool:
        return content_type is not None and content_type.lower().startswith("application/json")

    async def validate_request(self, request: Request, is_post: bool = False) -> Response | None:
        """Validate request headers for DNS rebinding protection.

        Returns None if validation passes, or an error Response if validation fails.
        """
        # Content-Type is checked even when DNS rebinding protection is disabled
        if is_post:
            content_type = request.headers.get("content-type")
            if not self._validate_content_type(content_type):
                return Response("Invalid Content-Type header", status_code=400)

        if not self.settings.enable_dns_rebinding_protection:
            return None

        host = request.headers.get("host")
        if not self._validate_host(host):
            return Response("Invalid Host header", status_code=421)

        origin = request.headers.get("origin")
        if not self._validate_origin(origin):
            return Response("Invalid Origin header", status_code=403)

        return None
