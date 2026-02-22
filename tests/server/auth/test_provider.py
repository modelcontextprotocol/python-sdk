"""Tests for mcp.server.auth.provider module."""

from mcp.server.auth.provider import AccessToken, construct_redirect_uri

# --- AccessToken tests ---


def test_access_token_basic_fields():
    """Test AccessToken with only required fields."""
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read"],
    )
    assert token.token == "tok_123"
    assert token.client_id == "client_1"
    assert token.scopes == ["read"]
    assert token.expires_at is None
    assert token.resource is None
    assert token.subject is None
    assert token.claims is None


def test_access_token_with_subject():
    """Test AccessToken with subject field for JWT sub claim."""
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read"],
        subject="user_42",
    )
    assert token.subject == "user_42"


def test_access_token_with_claims():
    """Test AccessToken with custom claims dict."""
    custom_claims = {
        "sub": "user_42",
        "iss": "https://auth.example.com",
        "org_id": "org_7",
        "roles": ["admin", "editor"],
    }
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read"],
        claims=custom_claims,
    )
    assert token.claims is not None
    assert token.claims == custom_claims
    assert token.claims["org_id"] == "org_7"
    assert token.claims["roles"] == ["admin", "editor"]


def test_access_token_with_subject_and_claims():
    """Test AccessToken with both subject and claims for convenience."""
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read", "write"],
        subject="user_42",
        claims={"sub": "user_42", "iss": "https://auth.example.com"},
    )
    assert token.subject == "user_42"
    assert token.claims is not None
    assert token.claims["sub"] == token.subject


def test_access_token_backward_compatible():
    """Test that existing code creating AccessToken without new fields still works."""
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read"],
        expires_at=1700000000,
        resource="https://api.example.com",
    )
    assert token.expires_at == 1700000000
    assert token.resource == "https://api.example.com"
    # New fields default to None
    assert token.subject is None
    assert token.claims is None


def test_access_token_serialization_roundtrip():
    """Test that AccessToken with new fields survives JSON serialization."""
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read"],
        subject="user_42",
        claims={"org_id": "org_7", "custom": True},
    )
    data = token.model_dump()
    restored = AccessToken.model_validate(data)
    assert restored.subject == "user_42"
    assert restored.claims == {"org_id": "org_7", "custom": True}


def test_access_token_empty_claims():
    """Test AccessToken with empty claims dict."""
    token = AccessToken(
        token="tok_123",
        client_id="client_1",
        scopes=["read"],
        claims={},
    )
    assert token.claims == {}


def test_construct_redirect_uri_no_existing_params():
    """Test construct_redirect_uri with no existing query parameters."""
    base_uri = "http://localhost:8000/callback"
    result = construct_redirect_uri(base_uri, code="auth_code", state="test_state")

    assert "http://localhost:8000/callback?code=auth_code&state=test_state" == result


def test_construct_redirect_uri_with_existing_params():
    """Test construct_redirect_uri with existing query parameters (regression test for #1279)."""
    base_uri = "http://localhost:8000/callback?session_id=1234"
    result = construct_redirect_uri(base_uri, code="auth_code", state="test_state")

    # Should preserve existing params and add new ones
    assert "session_id=1234" in result
    assert "code=auth_code" in result
    assert "state=test_state" in result
    assert result.startswith("http://localhost:8000/callback?")


def test_construct_redirect_uri_multiple_existing_params():
    """Test construct_redirect_uri with multiple existing query parameters."""
    base_uri = "http://localhost:8000/callback?session_id=1234&user=test"
    result = construct_redirect_uri(base_uri, code="auth_code")

    assert "session_id=1234" in result
    assert "user=test" in result
    assert "code=auth_code" in result


def test_construct_redirect_uri_with_none_values():
    """Test construct_redirect_uri filters out None values."""
    base_uri = "http://localhost:8000/callback"
    result = construct_redirect_uri(base_uri, code="auth_code", state=None)

    assert result == "http://localhost:8000/callback?code=auth_code"
    assert "state" not in result


def test_construct_redirect_uri_empty_params():
    """Test construct_redirect_uri with no additional parameters."""
    base_uri = "http://localhost:8000/callback?existing=param"
    result = construct_redirect_uri(base_uri)

    assert result == "http://localhost:8000/callback?existing=param"


def test_construct_redirect_uri_duplicate_param_names():
    """Test construct_redirect_uri when adding param that already exists."""
    base_uri = "http://localhost:8000/callback?code=existing"
    result = construct_redirect_uri(base_uri, code="new_code")

    # Should contain both values (this is expected behavior of parse_qs/urlencode)
    assert "code=existing" in result
    assert "code=new_code" in result


def test_construct_redirect_uri_multivalued_existing_params():
    """Test construct_redirect_uri with existing multi-valued parameters."""
    base_uri = "http://localhost:8000/callback?scope=read&scope=write"
    result = construct_redirect_uri(base_uri, code="auth_code")

    assert "scope=read" in result
    assert "scope=write" in result
    assert "code=auth_code" in result


def test_construct_redirect_uri_encoded_values():
    """Test construct_redirect_uri handles URL encoding properly."""
    base_uri = "http://localhost:8000/callback"
    result = construct_redirect_uri(base_uri, state="test state with spaces")

    # urlencode uses + for spaces by default
    assert "state=test+state+with+spaces" in result
