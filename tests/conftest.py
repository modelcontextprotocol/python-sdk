import pytest
from mcp.etdi.types import ETDIToolDefinition, Permission, SecurityInfo, OAuthInfo, OAuthConfig


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def valid_oauth_config():
    """Valid OAuth configuration for testing"""
    return OAuthConfig(
        provider="auth0",
        client_id="test-client-id",
        client_secret="test-client-secret",
        domain="test.auth0.com",
        scopes=["read:tools", "execute:tools"],
        audience="https://test-api.example.com"
    )


@pytest.fixture
def invalid_oauth_config():
    """Invalid OAuth configuration for testing"""
    return OAuthConfig(
        provider="invalid",
        client_id="",
        client_secret="",
        domain=""
    )


@pytest.fixture
def valid_tool():
    """Valid ETDI tool definition for testing"""
    return ETDIToolDefinition(
        id="valid-tool",
        name="Valid Test Tool",
        version="1.0.0",
        description="A valid tool for testing",
        provider={"id": "test-provider", "name": "Test Provider"},
        schema={"type": "object", "properties": {"input": {"type": "string"}}},
        permissions=[
            Permission(
                name="read_data",
                description="Permission to read data",
                scope="data:read",
                required=True
            )
        ],
        security=SecurityInfo(
            oauth=OAuthInfo(
                token="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJodHRwczovL3Rlc3QuYXV0aDAuY29tLyIsInN1YiI6InZhbGlkLXRvb2wiLCJhdWQiOiJodHRwczovL3Rlc3QtYXBpLmV4YW1wbGUuY29tIiwiZXhwIjo5OTk5OTk5OTk5LCJpYXQiOjE2MzQ1NjcwMDAsInNjb3BlIjoiZGF0YTpyZWFkIiwidG9vbF9pZCI6InZhbGlkLXRvb2wiLCJ0b29sX3ZlcnNpb24iOiIxLjAuMCJ9.signature",
                provider="auth0"
            )
        )
    )


@pytest.fixture
def malicious_tool():
    """Malicious/insecure tool definition for testing"""
    return ETDIToolDefinition(
        id="malicious-tool",
        name="Malicious Tool",
        version="0.1",  # Invalid version format
        description="",  # Missing description
        provider={"id": "", "name": ""},  # Missing provider info
        schema={"type": "object"},
        permissions=[
            Permission(
                name="admin_access",
                description="",  # Missing description
                scope="*",  # Overly broad scope
                required=True
            )
        ],
        security=None  # No security
    )
