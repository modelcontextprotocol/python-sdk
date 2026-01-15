"""Tests for issue #1574: Python SDK incorrectly validates Resource URIs.

The Python SDK uses Pydantic's AnyUrl for URI fields, which rejects relative paths
like 'users/me' that are valid according to the MCP spec and accepted by the
TypeScript SDK.

The spec defines uri fields as plain strings with no JSON Schema format validation.
"""

from mcp import types


class TestResourceUriValidation:
    """Test that Resource URI fields accept all valid MCP URIs."""

    def test_relative_path_uri(self):
        """
        REPRODUCER: Relative paths like 'users/me' should be accepted.

        Currently fails with:
        ValidationError: Input should be a valid URL, relative URL without a base
        """
        # This should NOT raise - relative paths are valid per MCP spec
        resource = types.Resource(name="test", uri="users/me")
        assert str(resource.uri) == "users/me"

    def test_custom_scheme_uri(self):
        """Custom scheme URIs should be accepted."""
        resource = types.Resource(name="test", uri="custom://resource")
        assert str(resource.uri) == "custom://resource"

    def test_file_url(self):
        """File URLs should be accepted."""
        resource = types.Resource(name="test", uri="file:///path/to/file")
        assert str(resource.uri) == "file:///path/to/file"

    def test_http_url(self):
        """HTTP URLs should be accepted."""
        resource = types.Resource(name="test", uri="https://example.com/resource")
        assert str(resource.uri) == "https://example.com/resource"


class TestReadResourceRequestParamsUri:
    """Test that ReadResourceRequestParams.uri accepts all valid MCP URIs."""

    def test_relative_path_uri(self):
        """Relative paths should be accepted in read requests."""
        params = types.ReadResourceRequestParams(uri="users/me")
        assert str(params.uri) == "users/me"


class TestResourceContentsUri:
    """Test that ResourceContents.uri accepts all valid MCP URIs."""

    def test_relative_path_uri(self):
        """Relative paths should be accepted in resource contents."""
        contents = types.TextResourceContents(uri="users/me", text="content")
        assert str(contents.uri) == "users/me"


class TestSubscribeRequestParamsUri:
    """Test that SubscribeRequestParams.uri accepts all valid MCP URIs."""

    def test_relative_path_uri(self):
        """Relative paths should be accepted in subscribe requests."""
        params = types.SubscribeRequestParams(uri="users/me")
        assert str(params.uri) == "users/me"


class TestUnsubscribeRequestParamsUri:
    """Test that UnsubscribeRequestParams.uri accepts all valid MCP URIs."""

    def test_relative_path_uri(self):
        """Relative paths should be accepted in unsubscribe requests."""
        params = types.UnsubscribeRequestParams(uri="users/me")
        assert str(params.uri) == "users/me"


class TestResourceUpdatedNotificationParamsUri:
    """Test that ResourceUpdatedNotificationParams.uri accepts all valid MCP URIs."""

    def test_relative_path_uri(self):
        """Relative paths should be accepted in resource updated notifications."""
        params = types.ResourceUpdatedNotificationParams(uri="users/me")
        assert str(params.uri) == "users/me"
