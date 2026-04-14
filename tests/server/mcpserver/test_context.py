"""Tests for the mcpserver Context class."""

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import Context


class TestContextSubject:
    """Tests for Context.subject property."""

    def test_subject_returns_none_when_unauthenticated(self):
        ctx = Context()
        assert ctx.subject is None

    def test_subject_returns_none_when_token_has_no_subject(self):
        user = AuthenticatedUser(AccessToken(token="tok", client_id="client", scopes=["read"]))
        token = auth_context_var.set(user)
        try:
            ctx = Context()
            assert ctx.subject is None
        finally:
            auth_context_var.reset(token)

    def test_subject_returns_value_from_access_token(self):
        user = AuthenticatedUser(AccessToken(token="tok", client_id="client", scopes=["read"], subject="user-123"))
        token = auth_context_var.set(user)
        try:
            ctx = Context()
            assert ctx.subject == "user-123"
        finally:
            auth_context_var.reset(token)

    def test_subject_reflects_current_context(self):
        ctx = Context()
        assert ctx.subject is None

        user = AuthenticatedUser(AccessToken(token="a", client_id="c", scopes=[], subject="alice"))
        cv_token = auth_context_var.set(user)
        try:
            assert ctx.subject == "alice"
        finally:
            auth_context_var.reset(cv_token)

        assert ctx.subject is None
