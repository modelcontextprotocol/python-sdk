from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
from pydantic import AnyUrl, FileUrl

from mcp.server.fastmcp.resources import (
    FileResource,
    FunctionResource,
    ResourceManager,
    ResourceTemplate,
)


@pytest.fixture
def temp_file():
    """Create a temporary file for testing.

    File is automatically cleaned up after the test if it still exists.
    """
    content = "test content"
    with NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(content)
        path = Path(f.name).resolve()
    yield path
    try:
        path.unlink()
    except FileNotFoundError:
        pass  # File was already deleted by the test


class TestResourceManager:
    """Test ResourceManager functionality."""

    def test_add_resource(self, temp_file: Path):
        """Test adding a resource."""
        manager = ResourceManager()
        resource = FileResource(
            uri=FileUrl(f"file://{temp_file}"),
            name="test",
            path=temp_file,
        )
        added = manager.add_resource(resource)
        assert added == resource
        assert manager.list_resources() == [resource]

    def test_add_duplicate_resource(self, temp_file: Path):
        """Test adding the same resource twice."""
        manager = ResourceManager()
        resource = FileResource(
            uri=FileUrl(f"file://{temp_file}"),
            name="test",
            path=temp_file,
        )
        first = manager.add_resource(resource)
        second = manager.add_resource(resource)
        assert first == second
        assert manager.list_resources() == [resource]

    def test_warn_on_duplicate_resources(self, temp_file: Path, caplog):
        """Test warning on duplicate resources."""
        manager = ResourceManager()
        resource = FileResource(
            uri=FileUrl(f"file://{temp_file}"),
            name="test",
            path=temp_file,
        )
        manager.add_resource(resource)
        manager.add_resource(resource)
        assert "Resource already exists" in caplog.text

    def test_disable_warn_on_duplicate_resources(self, temp_file: Path, caplog):
        """Test disabling warning on duplicate resources."""
        manager = ResourceManager(warn_on_duplicate_resources=False)
        resource = FileResource(
            uri=FileUrl(f"file://{temp_file}"),
            name="test",
            path=temp_file,
        )
        manager.add_resource(resource)
        manager.add_resource(resource)
        assert "Resource already exists" not in caplog.text

    @pytest.mark.anyio
    async def test_get_resource(self, temp_file: Path):
        """Test getting a resource by URI."""
        manager = ResourceManager()
        resource = FileResource(
            uri=FileUrl(f"file://{temp_file}"),
            name="test",
            path=temp_file,
        )
        manager.add_resource(resource)
        retrieved = await manager.get_resource(resource.uri)
        assert retrieved == resource

    @pytest.mark.anyio
    async def test_get_resource_from_template(self):
        """Test getting a resource through a template."""
        manager = ResourceManager()

        def greet(name: str) -> str:
            return f"Hello, {name}!"

        template = ResourceTemplate.from_function(
            fn=greet,
            uri_template="greet://{name}",
            name="greeter",
        )
        manager._templates[template.uri_template] = template

        resource = await manager.get_resource(AnyUrl("greet://world"))
        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Hello, world!"

    @pytest.mark.anyio
    async def test_get_unknown_resource(self):
        """Test getting a non-existent resource."""
        manager = ResourceManager()
        with pytest.raises(ValueError, match="Unknown resource"):
            await manager.get_resource(AnyUrl("unknown://test"))

    def test_list_resources(self, temp_file: Path):
        """Test listing all resources."""
        manager = ResourceManager()
        resource1 = FileResource(
            uri=FileUrl(f"file://{temp_file}"),
            name="test1",
            path=temp_file,
        )
        resource2 = FileResource(
            uri=FileUrl(f"file://{temp_file}2"),
            name="test2",
            path=temp_file,
        )
        manager.add_resource(resource1)
        manager.add_resource(resource2)
        resources = manager.list_resources()
        assert len(resources) == 2
        assert resources == [resource1, resource2]

    def test_list_resources_with_prefix(self, temp_file: Path):
        """Test listing resources with prefix filtering."""
        manager = ResourceManager()

        # Add resources with different URIs
        resource1 = FileResource(
            uri=FileUrl("file:///data/images/test.jpg"),
            name="test_image",
            path=temp_file,
        )
        resource2 = FileResource(
            uri=FileUrl("file:///data/docs/test.txt"),
            name="test_doc",
            path=temp_file,
        )
        resource3 = FileResource(
            uri=FileUrl("file:///other/test.txt"),
            name="other_test",
            path=temp_file,
        )

        manager.add_resource(resource1)
        manager.add_resource(resource2)
        manager.add_resource(resource3)

        # Test uri_paths filtering
        data_resources = manager.list_resources(uri_paths=[AnyUrl("file:///data/")])
        assert len(data_resources) == 2
        assert resource1 in data_resources
        assert resource2 in data_resources

        # More specific prefix
        image_resources = manager.list_resources(uri_paths=[AnyUrl("file:///data/images/")])
        assert len(image_resources) == 1
        assert resource1 in image_resources

        # No matches
        no_matches = manager.list_resources(uri_paths=[AnyUrl("file:///nonexistent/")])
        assert len(no_matches) == 0

        # Multiple uri_paths
        multi_resources = manager.list_resources(uri_paths=[AnyUrl("file:///data/"), AnyUrl("file:///other/")])
        assert len(multi_resources) == 3
        assert all(r in multi_resources for r in [resource1, resource2, resource3])

    def test_list_templates_with_prefix(self):
        """Test listing templates with prefix filtering."""
        manager = ResourceManager()

        # Add templates with different URI patterns
        def user_func(user_id: str) -> str:
            return f"User {user_id}"

        def post_func(user_id: str, post_id: str) -> str:
            return f"User {user_id} Post {post_id}"

        def product_func(product_id: str) -> str:
            return f"Product {product_id}"

        template1 = manager.add_template(user_func, uri_template="http://api.com/users/{user_id}", name="user_template")
        template2 = manager.add_template(
            post_func, uri_template="http://api.com/users/{user_id}/posts/{post_id}", name="post_template"
        )
        template3 = manager.add_template(
            product_func, uri_template="http://api.com/products/{product_id}", name="product_template"
        )

        # Test listing all templates
        all_templates = manager.list_templates()
        assert len(all_templates) == 3

        # Test uri_paths filtering - matches both user templates
        user_templates = manager.list_templates(uri_paths=[AnyUrl("http://api.com/users/")])
        assert len(user_templates) == 2
        assert template1 in user_templates
        assert template2 in user_templates

        # Test partial materialization - only matches post template
        # The template users/{user_id} generates "users/123" not "users/123/"
        # But users/{user_id}/posts/{post_id} can generate "users/123/posts/456"
        user_123_templates = manager.list_templates(uri_paths=[AnyUrl("http://api.com/users/123/")])
        assert len(user_123_templates) == 1
        assert template2 in user_123_templates  # users/{user_id}/posts/{post_id} matches

        # Without trailing slash, it gets added automatically so only posts template matches
        user_123_no_slash = manager.list_templates(uri_paths=[AnyUrl("http://api.com/users/123")])
        assert len(user_123_no_slash) == 1
        assert template2 in user_123_no_slash  # Only posts template has path after users/123/

        # Test product prefix
        product_templates = manager.list_templates(uri_paths=[AnyUrl("http://api.com/products/")])
        assert len(product_templates) == 1
        assert template3 in product_templates

        # No matches
        no_matches = manager.list_templates(uri_paths=[AnyUrl("http://api.com/orders/")])
        assert len(no_matches) == 0

        # Multiple uri_paths
        users_and_products = manager.list_templates(
            uri_paths=[AnyUrl("http://api.com/users/"), AnyUrl("http://api.com/products/")]
        )
        assert len(users_and_products) == 3
        assert all(t in users_and_products for t in all_templates)
