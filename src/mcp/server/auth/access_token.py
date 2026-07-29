"""The access token of the request being served, exposed via a contextvar.

This module is deliberately transport-agnostic: it imports no HTTP framework,
so `mcp.server.request_state` (and any tool handler) can read the caller's
token without loading the web stack. On HTTP transports the contextvar is
populated by `mcp.server.auth.middleware.auth_context.AuthContextMiddleware`,
which also re-exports both names under their long-standing import path.
"""

import contextvars
from typing import TYPE_CHECKING

from mcp.server.auth.provider import AccessToken

if TYPE_CHECKING:
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

# Create a contextvar to store the authenticated user
# The default is None, indicating no authenticated user is present
auth_context_var: contextvars.ContextVar["AuthenticatedUser | None"] = contextvars.ContextVar(
    "auth_context", default=None
)


def get_access_token() -> AccessToken | None:
    """Get the access token from the current context.

    Returns:
        The access token if an authenticated user is available, None otherwise.
    """
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None
