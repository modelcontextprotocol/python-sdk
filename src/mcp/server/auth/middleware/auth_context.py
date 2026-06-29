import contextvars

from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

auth_context_var = contextvars.ContextVar[AuthenticatedUser | None]("auth_context", default=None)


def get_access_token() -> AccessToken | None:
    """Get the authenticated user's access token from the current context, or None."""
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None


class AuthContextMiddleware:
    """Stores the authenticated user in a contextvar for the duration of the request.

    Must be added after AuthenticationMiddleware so `scope["user"]` is populated.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        user = scope.get("user")
        if isinstance(user, AuthenticatedUser):
            token = auth_context_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                auth_context_var.reset(token)
        else:
            await self.app(scope, receive, send)
