import time
from typing import Any

from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    SimpleUser,
)
from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection
from starlette.types import Receive, Scope, Send

from mcp.server.auth.provider import AccessToken, OAuthAuthorizationServerProvider


class AuthenticatedUser(SimpleUser):
    """User with authentication info."""

    def __init__(self, auth_info: AccessToken):
        super().__init__(auth_info.client_id)
        self.access_token = auth_info
        self.scopes = auth_info.scopes


class BearerAuthBackend(AuthenticationBackend):
    """
    Authentication backend that validates Bearer tokens.
    """

    def __init__(
        self,
        provider: OAuthAuthorizationServerProvider[Any, Any, Any],
    ):
        self.provider = provider

    async def authenticate(self, conn: HTTPConnection):
        auth_header = conn.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Remove "Bearer " prefix

        # Validate the token with the provider
        auth_info = await self.provider.load_access_token(token)

        if not auth_info:
            return None

        if auth_info.expires_at and auth_info.expires_at < int(time.time()):
            return None

        return AuthCredentials(auth_info.scopes), AuthenticatedUser(auth_info)


class RequireAuthMiddleware:
    """
    Middleware that requires a valid Bearer token in the Authorization header.

    This will validate the token with the auth provider and store the resulting
    auth info in the request state.
    """

    def __init__(self, app: Any, required_scopes: list[str]):
        """
        Initialize the middleware.

        Args:
            app: ASGI application
            provider: Authentication provider to validate tokens
            required_scopes: Optional list of scopes that the token must have
        """
        self.app = app
        self.required_scopes = required_scopes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        auth_user = scope.get("user")
        if not isinstance(auth_user, AuthenticatedUser):
            raise HTTPException(status_code=401, detail="Unauthorized")
        auth_credentials = scope.get("auth")

        for required_scope in self.required_scopes:
            # auth_credentials should always be provided; this is just paranoia
            if (
                auth_credentials is None
                or required_scope not in auth_credentials.scopes
            ):
                raise HTTPException(status_code=403, detail="Insufficient scope")

        await self.app(scope, receive, send)
