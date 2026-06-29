from mcp.server.auth.provider import construct_redirect_uri


def test_construct_redirect_uri_no_existing_params():
    base_uri = "http://localhost:8000/callback"
    result = construct_redirect_uri(base_uri, code="auth_code", state="test_state")

    assert "http://localhost:8000/callback?code=auth_code&state=test_state" == result


def test_construct_redirect_uri_with_existing_params():
    """Regression test for #1279."""
    base_uri = "http://localhost:8000/callback?session_id=1234"
    result = construct_redirect_uri(base_uri, code="auth_code", state="test_state")

    assert "session_id=1234" in result
    assert "code=auth_code" in result
    assert "state=test_state" in result
    assert result.startswith("http://localhost:8000/callback?")


def test_construct_redirect_uri_multiple_existing_params():
    base_uri = "http://localhost:8000/callback?session_id=1234&user=test"
    result = construct_redirect_uri(base_uri, code="auth_code")

    assert "session_id=1234" in result
    assert "user=test" in result
    assert "code=auth_code" in result


def test_construct_redirect_uri_with_none_values():
    base_uri = "http://localhost:8000/callback"
    result = construct_redirect_uri(base_uri, code="auth_code", state=None)

    assert result == "http://localhost:8000/callback?code=auth_code"
    assert "state" not in result


def test_construct_redirect_uri_empty_params():
    base_uri = "http://localhost:8000/callback?existing=param"
    result = construct_redirect_uri(base_uri)

    assert result == "http://localhost:8000/callback?existing=param"


def test_construct_redirect_uri_duplicate_param_names():
    base_uri = "http://localhost:8000/callback?code=existing"
    result = construct_redirect_uri(base_uri, code="new_code")

    # Both values are kept — parse_qs/urlencode behavior
    assert "code=existing" in result
    assert "code=new_code" in result


def test_construct_redirect_uri_multivalued_existing_params():
    base_uri = "http://localhost:8000/callback?scope=read&scope=write"
    result = construct_redirect_uri(base_uri, code="auth_code")

    assert "scope=read" in result
    assert "scope=write" in result
    assert "code=auth_code" in result


def test_construct_redirect_uri_encoded_values():
    base_uri = "http://localhost:8000/callback"
    result = construct_redirect_uri(base_uri, state="test state with spaces")

    # urlencode uses + for spaces by default
    assert "state=test+state+with+spaces" in result
