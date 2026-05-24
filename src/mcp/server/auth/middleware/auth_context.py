import contextvars
from contextvars import Token
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

# Create a contextvar to store the authenticated user
# The default is None, indicating no authenticated user is present
auth_context_var = contextvars.ContextVar[AuthenticatedUser | None]("auth_context", default=None)


def get_access_token() -> AccessToken | None:
    """Get the access token from the current context.

    Returns:
        The access token if an authenticated user is available, None otherwise.
    """
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None


def push_auth_context_from_request(request: Request | None) -> Token[AuthenticatedUser | None] | None:
    """Set auth context for the current task from an incoming request.

    This is primarily used by server transports where request handlers may run
    in background tasks that are not part of the original ASGI request task.
    """
    if request is None:
        return None
    # Avoid Request.user, which asserts AuthenticationMiddleware is installed.
    user: Any | None = request.scope.get("user")
    if user is None:
        try:
            user = getattr(request, "user", None)
        except AssertionError:
            user = None
    if isinstance(user, AuthenticatedUser):
        return auth_context_var.set(user)
    return None


def pop_auth_context(token: Token[AuthenticatedUser | None] | None) -> None:
    if token is None:
        return
    auth_context_var.reset(token)


class AuthContextMiddleware:
    """Middleware that extracts the authenticated user from the request
    and sets it in a contextvar for easy access throughout the request lifecycle.

    This middleware should be added after the AuthenticationMiddleware in the
    middleware stack to ensure that the user is properly authenticated before
    being stored in the context.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        user = scope.get("user")
        if isinstance(user, AuthenticatedUser):
            # Set the authenticated user in the contextvar
            token = auth_context_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                auth_context_var.reset(token)
        else:
            # No authenticated user, just process the request
            await self.app(scope, receive, send)
