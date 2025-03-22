import contextvars

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

# Create a contextvar to store the authenticated user
# The default is None, indicating no authenticated user is present
auth_context_var = contextvars.ContextVar[AuthenticatedUser | None](
    "auth_context", default=None
)


def get_access_token() -> AccessToken | None:
    """
    Get the access token from the current context.

    Returns:
        The access token if an authenticated user is available, None otherwise.
    """
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None


class AuthContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts the authenticated user from the request
    and sets it in a contextvar for easy access throughout the request lifecycle.

    This middleware should be added after the AuthenticationMiddleware in the
    middleware stack to ensure that the user is properly authenticated before
    being stored in the context.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Get the authenticated user from the request if it exists
        user = getattr(request, "user", None)

        # Only set the context var if the user is an AuthenticatedUser
        if isinstance(user, AuthenticatedUser):
            # Set the authenticated user in the contextvar
            token = auth_context_var.set(user)
            try:
                # Process the request
                response = await call_next(request)
                return response
            finally:
                # Reset the contextvar after the request is processed
                auth_context_var.reset(token)
        else:
            # No authenticated user, just process the request
            return await call_next(request)
