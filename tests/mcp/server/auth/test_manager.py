import pytest

from mcp.server.auth.manager import AuthorizationManager


@pytest.fixture
def auth_manager():
    """
    Fixture for the AuthorizationManager instance.
    """
    return AuthorizationManager("secret_key", "issuer", "audience")

def test_generate_token(auth_manager):
    token = auth_manager.generate_token({"user_id": 123})
    assert isinstance(token, str)

def test_validate_token(auth_manager):
    token = auth_manager.generate_token({"user_id": 123})
    claims = auth_manager.validate_token(token)
    assert claims.get("user_id") == 123

def test_claim_extraction(auth_manager):
    token = auth_manager.generate_token({"user_id": 123, "role": "admin"})
    claim = auth_manager.get_claim(token, "role")
    assert claim == "admin"

def test_expired_token(auth_manager):
    token = auth_manager.generate_token({"user_id": 123}, expires_in=-1)
    claims = auth_manager.validate_token(token)
    assert claims is None

def test_nonexistent_claim(auth_manager):
    token = auth_manager.generate_token({"user_id": 123})
    claim = auth_manager.get_claim(token, "email")
    assert claim is None

