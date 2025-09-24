import pytest

from mcp import types


@pytest.mark.parametrize(
    argnames="key",
    argvalues=[
        # Simple keys without reserved prefix
        "clientId",
        "request-id",
        "api_version",
        "product-id",
        "x-correlation-id",
        "my-key",
        "info",
        "data-1",
        "label-key",
        # Keys with reserved prefix
        "modelcontextprotocol.io/request-id",
        "mcp.dev/debug-mode",
        "api.modelcontextprotocol.org/api-version",
        "tools.mcp.com/validation-status",
        "my-company.mcp.io/internal-flag",
        "modelcontextprotocol.io/a",
        "mcp.dev/b-c",
        # Keys with non-reserved prefix
        "my-app.com/user-preferences",
        "internal.api/tracking-id",
        "org.example/resource-type",
        "custom.domain/status",
    ],
)
def test_metadata_valid_keys(key: str):
    """
    Asserts that valid metadata keys does not raise ValueErrors
    """
    types.RequestParams.Meta(**{key: "value"})


@pytest.mark.parametrize(
    argnames="key",
    argvalues=[
        # Invalid key names (without prefix)
        "-leading-hyphen",
        "trailing-hyphen-",
        "with space",
        "key/with/slash",
        "no@special-chars",
        "...",
        # Invalid prefixes
        "mcp.123/key",
        "my.custom./key",
        "my-app.com//key",
        # Invalid combination of prefix and name
        "mcp.dev/-invalid",
        "org.example/invalid-name-",
    ],
)
def test_metadata_invalid_keys(key: str):
    """
    Asserts that invalid metadata keys raise ValueErrors
    """
    with pytest.raises(ValueError):
        types.RequestParams.Meta(**{key: "value"})
