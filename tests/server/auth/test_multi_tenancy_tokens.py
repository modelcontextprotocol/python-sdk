"""Tests for multi-tenancy support in authentication token models."""

import pytest
from pydantic import AnyUrl

from mcp.server.auth.provider import AccessToken, AuthorizationCode, RefreshToken


def test_authorization_code_with_tenant_id():
    """Test AuthorizationCode creation with tenant_id."""
    code = AuthorizationCode(
        code="test_code",
        scopes=["read", "write"],
        expires_at=1234567890.0,
        client_id="test_client",
        code_challenge="challenge123",
        redirect_uri=AnyUrl("http://localhost:8000/callback"),
        redirect_uri_provided_explicitly=True,
        tenant_id="tenant-abc",
    )
    assert code.tenant_id == "tenant-abc"
    assert code.code == "test_code"
    assert code.scopes == ["read", "write"]


def test_authorization_code_without_tenant_id():
    """Test AuthorizationCode backward compatibility without tenant_id."""
    code = AuthorizationCode(
        code="test_code",
        scopes=["read"],
        expires_at=1234567890.0,
        client_id="test_client",
        code_challenge="challenge123",
        redirect_uri=AnyUrl("http://localhost:8000/callback"),
        redirect_uri_provided_explicitly=False,
    )
    assert code.tenant_id is None


def test_authorization_code_serialization_with_tenant_id():
    """Test AuthorizationCode serialization includes tenant_id."""
    code = AuthorizationCode(
        code="test_code",
        scopes=["read"],
        expires_at=1234567890.0,
        client_id="test_client",
        code_challenge="challenge123",
        redirect_uri=AnyUrl("http://localhost:8000/callback"),
        redirect_uri_provided_explicitly=True,
        tenant_id="tenant-xyz",
    )
    data = code.model_dump()
    assert data["tenant_id"] == "tenant-xyz"

    # Verify deserialization
    restored = AuthorizationCode.model_validate(data)
    assert restored.tenant_id == "tenant-xyz"


def test_refresh_token_with_tenant_id():
    """Test RefreshToken creation with tenant_id."""
    token = RefreshToken(
        token="refresh_token_123",
        client_id="test_client",
        scopes=["read", "write"],
        tenant_id="tenant-abc",
    )
    assert token.tenant_id == "tenant-abc"
    assert token.token == "refresh_token_123"


def test_refresh_token_without_tenant_id():
    """Test RefreshToken backward compatibility without tenant_id."""
    token = RefreshToken(
        token="refresh_token_123",
        client_id="test_client",
        scopes=["read"],
    )
    assert token.tenant_id is None


def test_refresh_token_serialization_with_tenant_id():
    """Test RefreshToken serialization includes tenant_id."""
    token = RefreshToken(
        token="refresh_token_123",
        client_id="test_client",
        scopes=["read"],
        expires_at=1234567890,
        tenant_id="tenant-xyz",
    )
    data = token.model_dump()
    assert data["tenant_id"] == "tenant-xyz"

    # Verify deserialization
    restored = RefreshToken.model_validate(data)
    assert restored.tenant_id == "tenant-xyz"


def test_access_token_with_tenant_id():
    """Test AccessToken creation with tenant_id."""
    token = AccessToken(
        token="access_token_123",
        client_id="test_client",
        scopes=["read", "write"],
        tenant_id="tenant-abc",
    )
    assert token.tenant_id == "tenant-abc"
    assert token.token == "access_token_123"


def test_access_token_without_tenant_id():
    """Test AccessToken backward compatibility without tenant_id."""
    token = AccessToken(
        token="access_token_123",
        client_id="test_client",
        scopes=["read"],
    )
    assert token.tenant_id is None


def test_access_token_serialization_with_tenant_id():
    """Test AccessToken serialization includes tenant_id."""
    token = AccessToken(
        token="access_token_123",
        client_id="test_client",
        scopes=["read"],
        expires_at=1234567890,
        resource="https://api.example.com",
        tenant_id="tenant-xyz",
    )
    data = token.model_dump()
    assert data["tenant_id"] == "tenant-xyz"

    # Verify deserialization
    restored = AccessToken.model_validate(data)
    assert restored.tenant_id == "tenant-xyz"


def test_access_token_with_resource_and_tenant_id():
    """Test AccessToken with both resource (RFC 8707) and tenant_id."""
    token = AccessToken(
        token="access_token_123",
        client_id="test_client",
        scopes=["read"],
        resource="https://api.example.com",
        tenant_id="tenant-abc",
    )
    assert token.resource == "https://api.example.com"
    assert token.tenant_id == "tenant-abc"


@pytest.mark.parametrize(
    "tenant_id",
    [
        "tenant-123",
        "org_abc_def",
        "a" * 100,  # Long tenant ID
        "tenant-with-dashes",
        "tenant.with.dots",
    ],
)
def test_access_token_various_tenant_id_formats(tenant_id: str):
    """Test AccessToken accepts various tenant_id formats."""
    token = AccessToken(
        token="access_token_123",
        client_id="test_client",
        scopes=["read"],
        tenant_id=tenant_id,
    )
    assert token.tenant_id == tenant_id
