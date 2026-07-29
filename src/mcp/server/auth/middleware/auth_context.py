from starlette.types import ASGIApp, Receive, Scope, Send

# The contextvar and its accessor are defined in a transport-agnostic module
# (no starlette) so request-state code can read the token without loading the
# web stack; they are re-exported here under their long-standing import path.
from mcp.server.auth.access_token import auth_context_var as auth_context_var
from mcp.server.auth.access_token import get_access_token as get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser


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
