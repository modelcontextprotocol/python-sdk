import pytest
from typing import Optional, Dict, Any
from mcp.server.auth.manager import AuthorizationManager

@pytest.fixture
def auth_manager():
    """
    Fixture to initialize the AuthorizationManager with consistent configuration.
    """
    return AuthorizationManager(
        secret_key="mysecret",
        issuer="https://myserver.com",
        audience="mcp"
    )

def test_generate_token(auth_manager):
    """
    Test that a token can be generated without errors.
    """
    token = auth_manager.generate_token({"user": "test_user"})
    print(f"[TEST] Generated Token: {token}")
    assert token is not None

def test_validate_token(auth_manager):
    """
    Test that a valid token returns the correct claims.
    """
    token = auth_manager.generate_token({"user": "test_user"})
    print(f"[TEST] Token: {token}")  # Debug print
    claims = auth_manager.validate_token(token)
    print(f"[TEST] Claims: {claims}")  # Debug print
    assert claims is not None
    assert claims.get("user") == "test_user"
    assert claims.get("iss") == "https://myserver.com"
    
    # Normalize the audience to always be a list for comparison
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience = [audience]
    assert audience == ["mcp"]


def test_claim_extraction(auth_manager):
    """
    Test that a specific claim can be extracted from the token.
    """
    token = auth_manager.generate_token({"user": "test_user", "role": "admin"})
    print(f"[TEST] Token: {token}")  # Debug print
    claim = auth_manager.get_claim(token, "role")
    print(f"[TEST] Extracted Claim: {claim}")  # Debug print
    assert claim == "admin"

def test_expired_token(auth_manager):
    """
    Test that an expired token is correctly identified.
    """
    token = auth_manager.generate_token({"user": "test_user"}, expires_in=-10)
    print(f"[TEST] Expired Token: {token}")  # Debug print
    claims = auth_manager.validate_token(token)
    print(f"[TEST] Claims from Expired Token: {claims}")  # Debug print
    assert claims is None

def test_nonexistent_claim(auth_manager):
    """
    Test that attempting to extract a non-existent claim returns None.
    """
    token = auth_manager.generate_token({"user": "test_user"})
    claim = auth_manager.get_claim(token, "nonexistent")
    print(f"[TEST] Non-existent Claim: {claim}")  # Debug print
    assert claim is None
