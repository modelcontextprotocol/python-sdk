import json
import time
from typing import Any, TypedDict

from pydantic import AnyHttpUrl
from starlette.authentication import AuthCredentials, AuthenticationBackend, BaseUser, SimpleUser
from starlette.requests import HTTPConnection
from starlette.types import Receive, Scope, Send

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.shared.auth_utils import check_token_audience


class AuthenticatedUser(SimpleUser):
    """User with authentication info."""

    def __init__(self, auth_info: AccessToken):
        super().__init__(auth_info.client_id)
        self.access_token = auth_info
        self.scopes = auth_info.scopes


class InvalidTokenUser(BaseUser):
    """Marker for a request that presented a Bearer token the verifier rejected,
    that has expired, or whose audience does not match this resource server.
    Carries the human-readable reason for the WWW-Authenticate error_description."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    @property
    def is_authenticated(self) -> bool:
        return False

    @property
    def display_name(self) -> str:
        return ""

    @property
    def identity(self) -> str:
        return ""


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
    token = user.access_token
    issuer = (token.claims or {}).get("iss")
    return AuthorizationContext(
        client_id=token.client_id,
        issuer=str(issuer) if issuer is not None else None,
        subject=token.subject,
    )


class BearerAuthBackend(AuthenticationBackend):
    """Authentication backend that validates Bearer tokens using a TokenVerifier."""

    def __init__(self, token_verifier: TokenVerifier, *, resource_server_url: AnyHttpUrl | None = None) -> None:
        self.token_verifier = token_verifier
        self.resource_server_url = resource_server_url

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, BaseUser] | None:
        auth_header = next(
            (conn.headers.get(key) for key in conn.headers if key.lower() == "authorization"),
            None,
        )
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return None  # no credentials presented → bare challenge per RFC 6750 §3

        token = auth_header[7:]
        auth_info = await self.token_verifier.verify_token(token)
        if auth_info is None:
            return AuthCredentials(), InvalidTokenUser("The access token is malformed or unknown")
        if auth_info.expires_at is not None and auth_info.expires_at < int(time.time()):
            return AuthCredentials(), InvalidTokenUser("The access token has expired")
        if (
            self.resource_server_url is not None
            and auth_info.resource is not None
            and not check_token_audience(auth_info.resource, self.resource_server_url)
        ):
            return AuthCredentials(), InvalidTokenUser("The access token was issued for a different resource")

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
        if isinstance(auth_user, InvalidTokenUser):
            await self._send_auth_error(send, status_code=401, error="invalid_token", description=auth_user.reason)
            return
        if not isinstance(auth_user, AuthenticatedUser):
            await self._send_auth_error(send, status_code=401)
            return

        auth_credentials = scope["auth"]
        for required_scope in self.required_scopes:
            if required_scope not in auth_credentials.scopes:
                await self._send_auth_error(
                    send,
                    status_code=403,
                    error="insufficient_scope",
                    description="The access token lacks a required scope",
                )
                return

        await self.app(scope, receive, send)

    async def _send_auth_error(
        self, send: Send, *, status_code: int, error: str | None = None, description: str | None = None
    ) -> None:
        """Send a Bearer challenge. RFC 6750 §3: error/error_description only when a token
        was presented; scope advertises what is required; resource_metadata for discovery."""
        parts: list[str] = []
        if error is not None:
            parts.append(f'error="{error}"')
        if description is not None:
            parts.append(f'error_description="{description}"')
        if self.required_scopes:
            parts.append(f'scope="{" ".join(self.required_scopes)}"')
        if self.resource_metadata_url:
            parts.append(f'resource_metadata="{self.resource_metadata_url}"')
        www_authenticate = f"Bearer {', '.join(parts)}" if parts else "Bearer"

        body: dict[str, str] = {}
        if error is not None:
            body["error"] = error
        if description is not None:
            body["error_description"] = description
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
