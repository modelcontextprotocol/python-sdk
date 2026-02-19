"""DNS rebinding protection for MCP server transports."""

import logging

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

    Only applies when `enable_dns_rebinding_protection` is `True`.
    """

    allowed_origins: list[str] = Field(default_factory=list)
    """List of allowed Origin header values.

    Only applies when `enable_dns_rebinding_protection` is `True`.
    """


# TODO(Marcelo): This should be a proper ASGI middleware. I'm sad to see this.
class TransportSecurityMiddleware:
    """Middleware to enforce DNS rebinding protection for MCP transport endpoints."""

    def __init__(self, settings: TransportSecuritySettings | None = None):
        # If not specified, disable DNS rebinding protection by default for backwards compatibility
        self.settings = settings or TransportSecuritySettings(enable_dns_rebinding_protection=False)

    def _validate_host(self, host: str | None) -> bool:  # pragma: no cover
        """Validate the Host header against allowed values."""
        if not host:
            logger.warning("Missing Host header in request")
            return False

        # Check exact match first
        print(host)
        if host in self.settings.allowed_hosts:
            return True
        
        for allowed in self.settings.allowed_hosts:

            # normalize incoming host
            host_without_https = (
                host.replace("https://", "")
                    .replace("http://", "")
                    .split("/")[0]
                    .strip()
            )
    
            # split request host + port
            if ":" in host_without_https:
                request_host, request_port = host_without_https.split(":", 1)
            else:
                request_host = host_without_https
                request_port = None
    
            # ---------- CASE 1: wildcard port (example.com:*) ----------
            if allowed.endswith(":*"):
                base_host = allowed[:-2]
                print(base_host)
    
                if request_host == base_host:
                    return True
    
            # ---------- CASE 2: specific port (example.com:443) ----------
            elif ":" in allowed:
                allowed_host, allowed_port = allowed.split(":", 1)
    
                if (
                    request_host == allowed_host
                    and request_port == allowed_port
                ):
                    return True
    
            # ---------- CASE 3: host only (allow any port) ----------
            else:
                if request_host == allowed:
                    return True
    
                logger.warning(f"Invalid Host header: {host}")
                return False
            
        logger.warning(f"Invalid Host header: {host}")
        return False    

    def _validate_origin(self, origin: str | None) -> bool:  # pragma: no cover
        """Validate the Origin header against allowed values."""
        # Origin can be absent for same-origin requests
        if not origin:
            return True

        # Check exact match first
        if origin in self.settings.allowed_origins:
            return True

        # Check wildcard port patterns
        for allowed in self.settings.allowed_origins:
            if allowed.endswith(":*"):
                # Extract base origin from pattern
                base_origin = allowed[:-2]
                # Check if the actual origin starts with base origin and has a port
                if origin.startswith(base_origin + ":"):
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
        if is_post:  # pragma: no branch
            content_type = request.headers.get("content-type")
            if not self._validate_content_type(content_type):
                return Response("Invalid Content-Type header", status_code=400)

        # Skip remaining validation if DNS rebinding protection is disabled
        if not self.settings.enable_dns_rebinding_protection:
            return None

        # Validate Host header  # pragma: no cover
        host = request.headers.get("host")  # pragma: no cover
        if not self._validate_host(host):  # pragma: no cover
            return Response("Invalid Host header", status_code=421)  # pragma: no cover

        # Validate Origin header  # pragma: no cover
        origin = request.headers.get("origin")  # pragma: no cover
        if not self._validate_origin(origin):  # pragma: no cover
            return Response("Invalid Origin header", status_code=403)  # pragma: no cover

        return None  # pragma: no cover
