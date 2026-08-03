import contextvars
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.auth.provider import AccessToken

if TYPE_CHECKING:
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

# Create a contextvar to store the authenticated user
# The default is None, indicating no authenticated user is present
auth_context_var: "contextvars.ContextVar[AuthenticatedUser | None]" = contextvars.ContextVar(
    "auth_context", default=None
)


def get_access_token() -> AccessToken | None:
    """Get the access token from the current context.

    Returns:
        The access token if an authenticated user is available, None otherwise.
    """
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None


class AuthContextMiddleware:
    """Middleware that extracts the authenticated user from the request
    and sets it in a contextvar for easy access throughout the request lifecycle.

    This middleware should be added after the AuthenticationMiddleware in the
    middleware stack to ensure that the user is properly authenticated before
    being stored in the context.
    """

    def __init__(self, app: ASGIApp):
        # `AuthenticatedUser` (starlette's authentication/request stack) is
        # imported once per app here rather than at module top: import-time
        # cost, so `get_access_token` above stays importable by transport-
        # agnostic code (request_state) without loading starlette's HTTP stack.
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

        self.app = app
        self._authenticated_user = AuthenticatedUser

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        user = scope.get("user")
        if isinstance(user, self._authenticated_user):
            # Set the authenticated user in the contextvar
            token = auth_context_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                auth_context_var.reset(token)
        else:
            # No authenticated user, just process the request
            await self.app(scope, receive, send)
