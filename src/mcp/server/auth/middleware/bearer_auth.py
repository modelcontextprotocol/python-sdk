import json
import time
from typing import Any

from pydantic import AnyHttpUrl
from starlette.authentication import AuthCredentials, AuthenticationBackend, SimpleUser
from starlette.requests import HTTPConnection
from starlette.types import Receive, Scope, Send

from mcp.server.auth.provider import AccessToken, TokenVerifier


class AuthenticatedUser(SimpleUser):
    """User with authentication info."""

    def __init__(self, auth_info: AccessToken):
        super().__init__(auth_info.client_id)
        self.access_token = auth_info
        self.scopes = auth_info.scopes


class BearerAuthBackend(AuthenticationBackend):
    """Authentication backend that validates Bearer tokens using a TokenVerifier."""

    def __init__(self, token_verifier: TokenVerifier):
        self.token_verifier = token_verifier

    async def authenticate(self, conn: HTTPConnection):
        auth_header = next(
            (conn.headers.get(key) for key in conn.headers if key.lower() == "authorization"),
            None,
        )
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return None

        token = auth_header[7:]  # Remove "Bearer " prefix

        # Validate the token with the verifier
        auth_info = await self.token_verifier.verify_token(token)

        if not auth_info:
            return None

        if auth_info.expires_at and auth_info.expires_at < int(time.time()):
            return None

        return AuthCredentials(auth_info.scopes), AuthenticatedUser(auth_info)


class RequireAuthMiddleware:
    """Middleware that requires a valid Bearer token in the Authorization header.

    This will validate the token with the auth provider and store the resulting
    auth info in the request state.
    """

    def __init__(
        self,
        app: Any,
        required_scopes: list[str],
        resource_metadata_url: AnyHttpUrl | None = None,
        auth_protocols: list[str] | None = None,
        default_protocol: str | None = None,
        protocol_preferences: dict[str, int] | None = None,
    ):
        """Initialize the middleware.

        Args:
            app: ASGI application
            required_scopes: List of scopes that the token must have
            resource_metadata_url: Optional protected resource metadata URL for WWW-Authenticate header
            auth_protocols: List of supported authentication protocol IDs (MCP extension)
            default_protocol: Default authentication protocol ID (MCP extension)
            protocol_preferences: Dictionary mapping protocol IDs to priority values (MCP extension)
        """
        self.app = app
        self.required_scopes = required_scopes
        self.resource_metadata_url = resource_metadata_url
        self.auth_protocols = auth_protocols
        self.default_protocol = default_protocol
        self.protocol_preferences = protocol_preferences

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        auth_user = scope.get("user")
        if not isinstance(auth_user, AuthenticatedUser):
            await self._send_auth_error(
                send, status_code=401, error="invalid_token", description="Authentication required"
            )
            return

        auth_credentials = scope.get("auth")

        for required_scope in self.required_scopes:
            # auth_credentials should always be provided; this is just paranoia
            if auth_credentials is None or required_scope not in auth_credentials.scopes:
                await self._send_auth_error(
                    send, status_code=403, error="insufficient_scope", description=f"Required scope: {required_scope}"
                )
                return

        await self.app(scope, receive, send)

    async def _send_auth_error(self, send: Send, status_code: int, error: str, description: str) -> None:
        """Send an authentication error response with WWW-Authenticate header."""
        # Build WWW-Authenticate header value
        www_auth_parts = [f'error="{error}"', f'error_description="{description}"']
        if self.resource_metadata_url:  # pragma: no cover
            www_auth_parts.append(f'resource_metadata="{self.resource_metadata_url}"')

        # Add protocol-related fields (MCP extension)
        if self.auth_protocols:
            protocols_str = " ".join(self.auth_protocols)
            www_auth_parts.append(f'auth_protocols="{protocols_str}"')
        if self.default_protocol:
            www_auth_parts.append(f'default_protocol="{self.default_protocol}"')
        if self.protocol_preferences:
            prefs_str = ",".join(f"{proto}:{priority}" for proto, priority in self.protocol_preferences.items())
            www_auth_parts.append(f'protocol_preferences="{prefs_str}"')

        # Keep scheme as Bearer for backwards compatibility.
        www_authenticate = f"Bearer {', '.join(www_auth_parts)}"

        # Send response
        body = {"error": error, "error_description": description}
        body_bytes = json.dumps(body).encode()

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode()),
                    (b"www-authenticate", www_authenticate.encode()),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body_bytes,
            }
        )
