import pytest
from pydantic import AnyHttpUrl, ValidationError

from mcp.server.auth.settings import AuthSettings


def test_validate_token_resource_requires_a_resource_server_url():
    """SDK-defined: asking the bearer gate to compare tokens against `resource_server_url` without
    configuring one is refused at construction time rather than silently comparing nothing."""
    issuer_url = AnyHttpUrl("https://auth.example.com")
    AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=AnyHttpUrl("https://mcp.example.com/mcp"),
        validate_token_resource=True,
    )
    with pytest.raises(ValidationError, match="validate_token_resource requires resource_server_url"):
        AuthSettings(issuer_url=issuer_url, resource_server_url=None, validate_token_resource=True)
