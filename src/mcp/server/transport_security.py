"""Request checks shared by the HTTP server transports: Host/Origin header validation and body size limits."""

import logging
from collections import deque
from typing import Final

from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

DEFAULT_MAX_REQUEST_BODY_SIZE: Final = 4 * 1024 * 1024
"""Default maximum HTTP request body size in bytes (4 MiB)."""


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

    def _validate_host(self, host: str | None) -> bool:
        """Validate the Host header against allowed values."""
        if not host:
            logger.warning("Missing Host header in request")
            return False

        # Check exact match first
        if host in self.settings.allowed_hosts:
            return True

        # Check wildcard port patterns
        for allowed in self.settings.allowed_hosts:
            if allowed.endswith(":*"):
                # Extract base host from pattern
                base_host = allowed[:-2]
                # Check if the actual host starts with base host and has a port
                if host.startswith(base_host + ":"):
                    return True

        logger.warning(f"Invalid Host header: {host}")
        return False

    def _validate_origin(self, origin: str | None) -> bool:
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
        if is_post:
            content_type = request.headers.get("content-type")
            if not self._validate_content_type(content_type):
                return Response("Invalid Content-Type header", status_code=400)

        # Skip remaining validation if DNS rebinding protection is disabled
        if not self.settings.enable_dns_rebinding_protection:
            return None

        # Validate Host header
        host = request.headers.get("host")
        if not self._validate_host(host):
            return Response("Invalid Host header", status_code=421)

        # Validate Origin header
        origin = request.headers.get("origin")
        if not self._validate_origin(origin):
            return Response("Invalid Origin header", status_code=403)

        return None


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP request bodies before invoking an ASGI application."""

    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                pass
            else:
                if declared_size > self.max_body_size:
                    response = Response("Request body too large", status_code=413)
                    return await response(scope, receive, send)

        received_body = bytearray()
        received_request = False
        body_complete = False
        trailing_message: Message | None = None
        while True:
            message = await receive()
            if message["type"] != "http.request":
                trailing_message = message
                break

            received_request = True
            body = message.get("body", b"")
            if len(received_body) + len(body) > self.max_body_size:
                response = Response("Request body too large", status_code=413)
                return await response(scope, receive, send)
            received_body.extend(body)
            if not message.get("more_body", False):
                body_complete = True
                break

        cached_messages: deque[Message] = deque()
        if received_request:
            cached_messages.append(
                {"type": "http.request", "body": bytes(received_body), "more_body": not body_complete}
            )
        if trailing_message is not None:
            cached_messages.append(trailing_message)

        async def replay() -> Message:
            if cached_messages:
                return cached_messages.popleft()
            return await receive()

        await self.app(scope, replay, send)
