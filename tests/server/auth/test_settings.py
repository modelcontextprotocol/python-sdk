import warnings

import pytest
from pydantic import AnyHttpUrl, ValidationError

from mcp.server.auth.settings import AuthSettings
from mcp.shared.exceptions import MCPDeprecationWarning

ISSUER = AnyHttpUrl("https://auth.example.com")
RESOURCE = AnyHttpUrl("https://mcp.example.com/mcp")


def test_validate_token_resource_requires_a_resource_server_url():
    """SDK-defined: asking the bearer gate to compare tokens against `resource_server_url` without
    configuring one is refused at construction time rather than silently comparing nothing."""
    AuthSettings(issuer_url=ISSUER, resource_server_url=RESOURCE, validate_token_resource=True)
    with pytest.raises(ValidationError, match="validate_token_resource requires resource_server_url"):
        AuthSettings(issuer_url=ISSUER, resource_server_url=None, validate_token_resource=True)


def test_leaving_validate_token_resource_unset_warns_when_a_resource_server_url_is_configured():
    """Unset behaves as False but says so: a resource server that has not chosen gets an
    `MCPDeprecationWarning` pointing at its own `AuthSettings(...)` call (3.0 flips the default)."""
    with pytest.warns(MCPDeprecationWarning, match="validate_token_resource") as record:
        settings = AuthSettings(issuer_url=ISSUER, resource_server_url=RESOURCE)
    assert settings.validate_token_resource is None
    assert record[0].filename == __file__


@pytest.mark.parametrize("kwargs", [{"validate_token_resource": False}, {"resource_server_url": None}])
def test_an_explicit_choice_or_no_resource_server_url_does_not_warn(kwargs: dict[str, object]):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        AuthSettings.model_validate({"issuer_url": ISSUER, "resource_server_url": RESOURCE, **kwargs})
