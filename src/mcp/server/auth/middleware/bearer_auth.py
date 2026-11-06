import json
import logging
import time
from typing import Any, TypedDict

from pydantic import AnyHttpUrl, ValidationError
from starlette.authentication import AuthCredentials, AuthenticationBackend, SimpleUser
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.types import Receive, Scope, Send

from mcp.server.auth.provider import AccessToken, TokenVerifier, principal_components

logger = logging.getLogger(__name__)


class AuthenticatedUser(SimpleUser):
    """User with authentication info."""

    def __init__(self, auth_info: AccessToken):
        super().__init__(auth_info.client_id)
        self.access_token = auth_info
        self.scopes = auth_info.scopes


class AuthorizationContext(TypedDict):
    client_id: str
    issuer: str | None
    subject: str | None


def authorization_context(user: AuthenticatedUser) -> AuthorizationContext:
    """Identify the principal `user` represents, for transports to compare
    against the principal that created a session. Components the token
    verifier does not supply are `None`, so the comparison degrades to the
    remaining components.

    See `examples/servers/simple-auth/mcp_simple_auth/token_verifier.py` for
    a verifier that populates `subject` and `claims` from an introspection
    response."""
    client_id, issuer, subject = principal_components(user.access_token)
    return AuthorizationContext(client_id=client_id, issuer=issuer, subject=subject)


class BearerAuthBackend(AuthenticationBackend):
    """Authentication backend that validates Bearer tokens using a TokenVerifier.

    When `resource_server_url` is given, only a token whose `AccessToken.resource`
    (its RFC 8707 resource indicator / audience) is that URL is accepted.
    """

    def __init__(self, token_verifier: TokenVerifier, *, resource_server_url: AnyHttpUrl | None = None):
        self.token_verifier = token_verifier
        self.resource_server_url = resource_server_url

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

        if self.resource_server_url and not self._issued_for_this_resource(auth_info.resource):
            logger.warning(
                "Bearer token resource %r is not resource_server_url %s", auth_info.resource, self.resource_server_url
            )
            return None

        return AuthCredentials(auth_info.scopes), AuthenticatedUser(auth_info)

    def _issued_for_this_resource(self, resource: str | None) -> bool:
        """Compare as URLs (so case and default-port spelling do not matter), a trailing slash aside."""
        try:
            token_resource = str(AnyHttpUrl(resource or ""))
        except ValidationError:
            return False
        return token_resource.removesuffix("/") == str(self.resource_server_url).removesuffix("/")


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
    ):
        """Initialize the middleware.

        Args:
            app: ASGI application
            required_scopes: List of scopes that the token must have
            resource_metadata_url: Optional protected resource metadata URL for WWW-Authenticate header
        """
        self.app = app
        self.required_scopes = required_scopes
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        auth_user = scope.get("user")
        if not isinstance(auth_user, AuthenticatedUser):
            # RFC 6750 3.1: a request with no credentials SHOULD NOT include an
            # error code. Only a presented-but-invalid token gets
            # error="invalid_token". Advertise the required scopes either way.
            headers = Headers(scope=scope)
            presented = headers.get("authorization") is not None
            await self._send_auth_error(
                send,
                status_code=401,
                error="invalid_token" if presented else None,
                description="Authentication required" if presented else None,
                scope=self.required_scopes or None,
            )
            return

        auth_credentials = scope.get("auth")

        for required_scope in self.required_scopes:
            # auth_credentials should always be provided; this is just paranoia
            if auth_credentials is None or required_scope not in auth_credentials.scopes:
                await self._send_auth_error(
                    send,
                    status_code=403,
                    error="insufficient_scope",
                    description=f"Required scope: {required_scope}",
                    scope=[required_scope],
                )
                return

        await self.app(scope, receive, send)

    async def _send_auth_error(
        self,
        send: Send,
        status_code: int,
        error: str | None = None,
        description: str | None = None,
        scope: list[str] | None = None,
    ) -> None:
        """Send an authentication error response with WWW-Authenticate header."""
        # Build WWW-Authenticate header value
        www_auth_parts = []
        if error:
            www_auth_parts.append(f'error="{error}"')
        if description:
            www_auth_parts.append(f'error_description="{description}"')
        if self.resource_metadata_url:
            www_auth_parts.append(f'resource_metadata="{self.resource_metadata_url}"')
        if scope:
            # Join outside the f-string: nested same-type quotes in an f-string
            # need PEP 701 (Python 3.12+), and this project supports 3.11.
            scope_value = " ".join(scope)
            www_auth_parts.append(f'scope="{scope_value}"')

        www_authenticate = f"Bearer {', '.join(www_auth_parts)}"

        # Send response
        body = {} if error is None else {"error": error, "error_description": description}
        body_bytes = json.dumps(body).encode() if body else b""

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
