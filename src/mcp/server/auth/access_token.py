"""The access token of the request being served, exposed via a contextvar.

This module is deliberately transport- and auth-stack-agnostic: it imports no
HTTP framework and no OAuth model, so `mcp.server.request_state` (and any tool
handler) can read the caller's token without loading either. On HTTP transports
the contextvar is populated by
`mcp.server.auth.middleware.auth_context.AuthContextMiddleware`, which also
re-exports both names under their long-standing import path.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

import mcp

if TYPE_CHECKING:
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

# Create a contextvar to store the authenticated user
# The default is None, indicating no authenticated user is present
auth_context_var: contextvars.ContextVar[AuthenticatedUser | None] = contextvars.ContextVar(
    "auth_context", default=None
)


# The return type is spelled through the lazy `mcp.server` namespace so this
# module never imports the OAuth provider models, while
# `typing.get_type_hints(get_access_token)` still resolves it on demand.
def get_access_token() -> mcp.server.auth.provider.AccessToken | None:
    """Get the access token from the current context.

    Returns:
        The access token if an authenticated user is available, None otherwise.
    """
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None
