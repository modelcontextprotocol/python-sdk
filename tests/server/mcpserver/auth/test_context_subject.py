"""Context.subject reads the resource owner from the request's access token."""

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import Context


def test_subject_is_none_when_unauthenticated():
    assert Context().subject is None


def test_subject_is_none_when_token_has_no_subject():
    user = AuthenticatedUser(AccessToken(token="t", client_id="c", scopes=[]))
    cv_token = auth_context_var.set(user)
    try:
        assert Context().subject is None
    finally:
        auth_context_var.reset(cv_token)


def test_subject_reads_from_access_token():
    user = AuthenticatedUser(AccessToken(token="t", client_id="c", scopes=[], subject="user-123"))
    cv_token = auth_context_var.set(user)
    try:
        assert Context().subject == "user-123"
    finally:
        auth_context_var.reset(cv_token)


def test_subject_tracks_current_auth_context():
    ctx = Context()
    assert ctx.subject is None

    alice = AuthenticatedUser(AccessToken(token="a", client_id="c", scopes=[], subject="alice"))
    cv_token = auth_context_var.set(alice)
    try:
        assert ctx.subject == "alice"
    finally:
        auth_context_var.reset(cv_token)

    assert ctx.subject is None
