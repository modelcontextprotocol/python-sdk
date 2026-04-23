"""DNS rebinding protection for MCP server transports."""

import logging
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# TODO(Marcelo): We should flatten these settings. To be fair, I don't think we should even have this middleware.
class TransportSecuritySettings(BaseModel):
    """Settings for MCP transport security features.

    These settings help protect against DNS rebinding attacks by validating incoming request headers.
    """

    enable_dns_rebinding_protection: bool = True
    """Enable DNS rebinding protection (recommended for production)."""

    allowed_hosts: list[str] = Field(default_factory=list)
    """List of allowed Host header values.

    Supports exact matches, port wildcards, and subdomain wildcards:

    - ``"example.com"`` — exact match
    - ``"example.com:*"`` — any port on that host
    - ``"*.example.com"`` — any subdomain (or the base domain itself)

    Only applies when `enable_dns_rebinding_protection` is `True`.
    """

    allowed_origins: list[str] = Field(default_factory=list)
    """List of allowed Origin header values.

    Supports exact matches, port wildcards, and subdomain wildcards:

    - ``"https://example.com"`` — exact match
    - ``"https://example.com:*"`` — any port on that origin
    - ``"https://*.example.com"`` — any subdomain (or the base domain itself) with HTTPS

    Only applies when `enable_dns_rebinding_protection` is `True`.
    """


# TODO(Marcelo): This should be a proper ASGI middleware. I'm sad to see this.
class TransportSecurityMiddleware:
    """Middleware to enforce DNS rebinding protection for MCP transport endpoints."""

    def __init__(self, settings: TransportSecuritySettings | None = None):
        # If not specified, disable DNS rebinding protection by default for backwards compatibility
        self.settings = settings or TransportSecuritySettings(enable_dns_rebinding_protection=False)

    def _validate_host(self, host: str | None) -> bool:
        """Validate the Host header against allowed values."""
        if not host:
            logger.warning("Missing Host header in request")
            return False

        if host in self.settings.allowed_hosts:
            return True

        # Strip port for subdomain wildcard matching
        host_without_port = host.split(":")[0]

        for allowed in self.settings.allowed_hosts:
            if allowed.endswith(":*"):
                # Port wildcard: e.g., "example.com:*" matches "example.com:8080"
                base_host = allowed[:-2]
                if host.startswith(base_host + ":"):
                    return True
            elif allowed.startswith("*."):
                # Subdomain wildcard: e.g., "*.example.com" matches "example.com"
                # and "sub.example.com" (port is ignored)
                suffix = allowed[2:]
                if host_without_port == suffix or host_without_port.endswith("." + suffix):
                    return True

        logger.warning(f"Invalid Host header: {host}")
        return False

    def _validate_origin(self, origin: str | None) -> bool:
        """Validate the Origin header against allowed values."""
        # Origin can be absent for same-origin requests
        if not origin:
            return True

        if origin in self.settings.allowed_origins:
            return True

        for allowed in self.settings.allowed_origins:
            if allowed.endswith(":*"):
                # Port wildcard: e.g., "https://example.com:*" matches "https://example.com:8080"
                base_origin = allowed[:-2]
                if origin.startswith(base_origin + ":"):
                    return True
            elif "://*." in allowed:
                # Subdomain wildcard: e.g., "https://*.example.com" matches
                # "https://example.com" and "https://sub.example.com"
                parsed_allowed = urlparse(allowed)
                parsed_origin = urlparse(origin)
                if parsed_allowed.scheme != parsed_origin.scheme:
                    continue
                # hostname is "*.suffix" because "://*." is in the pattern
                suffix = (parsed_allowed.hostname or "")[2:]
                origin_hostname = parsed_origin.hostname or ""
                if origin_hostname == suffix or origin_hostname.endswith("." + suffix):
                    return True

        logger.warning(f"Invalid Origin header: {origin}")
        return False

    def _validate_content_type(self, content_type: str | None) -> bool:
        """Validate the Content-Type header for POST requests."""
        return content_type is not None and content_type.lower().startswith("application/json")

    async def validate_request(self, request: Request, is_post: bool = False) -> Response | None:
        """Validate request headers for DNS rebinding protection.

        Returns None if validation passes, or an error Response if validation fails.
        """
        # Always validate Content-Type for POST requests
        if is_post:
            content_type = request.headers.get("content-type")
            if not self._validate_content_type(content_type):
                return Response("Invalid Content-Type header", status_code=400)

        # Skip remaining validation if DNS rebinding protection is disabled
        if not self.settings.enable_dns_rebinding_protection:
            return None

        host = request.headers.get("host")
        if not self._validate_host(host):
            return Response("Invalid Host header", status_code=421)

        origin = request.headers.get("origin")
        if not self._validate_origin(origin):
            return Response("Invalid Origin header", status_code=403)

        return None
