"""
Tests for mcp.server.auth.provider module.
"""

from mcp.server.auth.provider import construct_redirect_uri


class TestConstructRedirectUri:
    """Tests for the construct_redirect_uri function."""

    def test_construct_redirect_uri_no_existing_params(self):
        """Test construct_redirect_uri with no existing query parameters."""
        base_uri = "http://localhost:8000/callback"
        result = construct_redirect_uri(base_uri, code="auth_code", state="test_state")

        assert "http://localhost:8000/callback?code=auth_code&state=test_state" == result

    def test_construct_redirect_uri_with_existing_params(self):
        """Test construct_redirect_uri with existing query parameters (regression test for #1279)."""
        base_uri = "http://localhost:8000/callback?session_id=1234"
        result = construct_redirect_uri(base_uri, code="auth_code", state="test_state")

        # Should preserve existing params and add new ones
        assert "session_id=1234" in result
        assert "code=auth_code" in result
        assert "state=test_state" in result
        assert result.startswith("http://localhost:8000/callback?")

    def test_construct_redirect_uri_multiple_existing_params(self):
        """Test construct_redirect_uri with multiple existing query parameters."""
        base_uri = "http://localhost:8000/callback?session_id=1234&user=test"
        result = construct_redirect_uri(base_uri, code="auth_code")

        assert "session_id=1234" in result
        assert "user=test" in result
        assert "code=auth_code" in result

    def test_construct_redirect_uri_with_none_values(self):
        """Test construct_redirect_uri filters out None values."""
        base_uri = "http://localhost:8000/callback"
        result = construct_redirect_uri(base_uri, code="auth_code", state=None)

        assert result == "http://localhost:8000/callback?code=auth_code"
        assert "state" not in result

    def test_construct_redirect_uri_empty_params(self):
        """Test construct_redirect_uri with no additional parameters."""
        base_uri = "http://localhost:8000/callback?existing=param"
        result = construct_redirect_uri(base_uri)

        assert result == "http://localhost:8000/callback?existing=param"

    def test_construct_redirect_uri_duplicate_param_names(self):
        """Test construct_redirect_uri when adding param that already exists."""
        base_uri = "http://localhost:8000/callback?code=existing"
        result = construct_redirect_uri(base_uri, code="new_code")

        # Should contain both values (this is expected behavior of parse_qs/urlencode)
        assert "code=existing" in result
        assert "code=new_code" in result

    def test_construct_redirect_uri_multivalued_existing_params(self):
        """Test construct_redirect_uri with existing multi-valued parameters."""
        base_uri = "http://localhost:8000/callback?scope=read&scope=write"
        result = construct_redirect_uri(base_uri, code="auth_code")

        assert "scope=read" in result
        assert "scope=write" in result
        assert "code=auth_code" in result

    def test_construct_redirect_uri_encoded_values(self):
        """Test construct_redirect_uri handles URL encoding properly."""
        base_uri = "http://localhost:8000/callback"
        result = construct_redirect_uri(base_uri, state="test state with spaces")

        # urlencode uses + for spaces by default
        assert "state=test+state+with+spaces" in result
