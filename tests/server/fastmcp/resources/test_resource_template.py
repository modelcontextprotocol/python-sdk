import json

import pytest
from pydantic import BaseModel

from mcp.server.fastmcp.resources import FunctionResource, ResourceTemplate


class TestResourceTemplate:
    """Test ResourceTemplate functionality."""

    def test_template_creation(self):
        """Test creating a template from a function."""

        def my_func(key: str, value: int) -> dict:
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )
        assert template.uri_template == "test://{key}/{value}"
        assert template.name == "test"
        assert template.mime_type == "text/plain"  # default
        test_input = {"key": "test", "value": 42}
        assert template.fn(**test_input) == my_func(**test_input)

    def test_template_matches(self):
        """Test matching URIs against a template."""

        def my_func(key: str, value: int) -> dict:
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )

        # Valid match
        params = template.matches("test://foo/123")
        assert params == {"key": "foo", "value": "123"}

        # No match
        assert template.matches("test://foo") is None
        assert template.matches("other://foo/123") is None

    @pytest.mark.anyio
    async def test_create_resource(self):
        """Test creating a resource from a template."""

        def my_func(key: str, value: int) -> dict:
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )

        resource = await template.create_resource(
            "test://foo/123",
            {"key": "foo", "value": 123},
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert isinstance(content, str)
        data = json.loads(content)
        assert data == {"key": "foo", "value": 123}

    @pytest.mark.anyio
    async def test_template_error(self):
        """Test error handling in template resource creation."""

        def failing_func(x: str) -> str:
            raise ValueError("Test error")

        template = ResourceTemplate.from_function(
            fn=failing_func,
            uri_template="fail://{x}",
            name="fail",
        )

        with pytest.raises(ValueError, match="Error creating resource from template"):
            await template.create_resource("fail://test", {"x": "test"})

    @pytest.mark.anyio
    async def test_async_text_resource(self):
        """Test creating a text resource from async function."""

        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        template = ResourceTemplate.from_function(
            fn=greet,
            uri_template="greet://{name}",
            name="greeter",
        )

        resource = await template.create_resource(
            "greet://world",
            {"name": "world"},
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Hello, world!"

    @pytest.mark.anyio
    async def test_async_binary_resource(self):
        """Test creating a binary resource from async function."""

        async def get_bytes(value: str) -> bytes:
            return value.encode()

        template = ResourceTemplate.from_function(
            fn=get_bytes,
            uri_template="bytes://{value}",
            name="bytes",
        )

        resource = await template.create_resource(
            "bytes://test",
            {"value": "test"},
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == b"test"

    @pytest.mark.anyio
    async def test_basemodel_conversion(self):
        """Test handling of BaseModel types."""

        class MyModel(BaseModel):
            key: str
            value: int

        def get_data(key: str, value: int) -> MyModel:
            return MyModel(key=key, value=value)

        template = ResourceTemplate.from_function(
            fn=get_data,
            uri_template="test://{key}/{value}",
            name="test",
        )

        resource = await template.create_resource(
            "test://foo/123",
            {"key": "foo", "value": 123},
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert isinstance(content, str)
        data = json.loads(content)
        assert data == {"key": "foo", "value": 123}

    @pytest.mark.anyio
    async def test_custom_type_conversion(self):
        """Test handling of custom types."""

        class CustomData:
            def __init__(self, value: str):
                self.value = value

            def __str__(self) -> str:
                return self.value

        def get_data(value: str) -> CustomData:
            return CustomData(value)

        template = ResourceTemplate.from_function(
            fn=get_data,
            uri_template="test://{value}",
            name="test",
        )

        resource = await template.create_resource(
            "test://hello",
            {"value": "hello"},
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == '"hello"'

    def test_matches_prefix_exact_template(self):
        """Test that templates match when prefix matches template exactly."""

        def dummy_func() -> str:
            return "data"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="http://api.example.com/users/{user_id}", name="test"
        )

        # Exact prefix of template
        assert template.matches_prefix("http://api.example.com/users/")
        assert template.matches_prefix("http://api.example.com/users")
        assert template.matches_prefix("http://api.example.com/")
        assert template.matches_prefix("http://")

    def test_matches_prefix_partial_materialization(self):
        """Test matching with partially materialized parameters."""

        def dummy_func(user_id: str, post_id: str) -> str:
            return f"User {user_id} Post {post_id}"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="http://api.example.com/users/{user_id}/posts/{post_id}", name="test"
        )

        # Partial materialization - user_id replaced with value
        assert template.matches_prefix("http://api.example.com/users/123/")
        assert template.matches_prefix("http://api.example.com/users/123/posts/")
        assert template.matches_prefix("http://api.example.com/users/alice/posts/")

        # Without trailing slash
        assert template.matches_prefix("http://api.example.com/users/123")
        assert template.matches_prefix("http://api.example.com/users/123/posts")

    def test_matches_prefix_no_match_different_structure(self):
        """Test that templates don't match when structure differs."""

        def dummy_func(user_id: str) -> str:
            return f"User {user_id}"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="http://api.example.com/users/{user_id}", name="test"
        )

        # Different path structure
        assert not template.matches_prefix("http://api.example.com/products/")
        assert not template.matches_prefix("http://api.example.com/users/123/invalid/")
        assert not template.matches_prefix("http://different.com/users/")

    def test_matches_prefix_complex_nested(self):
        """Test matching with complex nested templates."""

        def dummy_func(org_id: str, team_id: str, user_id: str) -> str:
            return f"Org {org_id} Team {team_id} User {user_id}"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="http://api.example.com/orgs/{org_id}/teams/{team_id}/users/{user_id}", name="test"
        )

        # Various levels of partial materialization
        assert template.matches_prefix("http://api.example.com/orgs/")
        assert template.matches_prefix("http://api.example.com/orgs/acme/")
        assert template.matches_prefix("http://api.example.com/orgs/acme/teams/")
        assert template.matches_prefix("http://api.example.com/orgs/acme/teams/dev/")
        assert template.matches_prefix("http://api.example.com/orgs/acme/teams/dev/users/")

    def test_matches_prefix_file_uri(self):
        """Test matching with file:// URI templates."""

        def dummy_func(category: str, filename: str) -> str:
            return f"File {category}/{filename}"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="file:///data/{category}/{filename}", name="test"
        )

        assert template.matches_prefix("file:///data/")
        assert template.matches_prefix("file:///data/images/")
        assert template.matches_prefix("file:///data/docs/")
        assert not template.matches_prefix("file:///other/")

    def test_matches_prefix_trailing_slash_semantics(self):
        """Test that trailing slashes have semantic meaning."""

        def dummy_func(id: str) -> str:
            return f"Item {id}"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="http://api.example.com/items/{id}", name="test"
        )

        # Prefix without trailing slash matches (looking for items or under items)
        assert template.matches_prefix("http://api.example.com/items")
        assert template.matches_prefix("http://api.example.com/items/123")

        # Prefix with trailing slash only matches if template generates something under it
        assert template.matches_prefix("http://api.example.com/items/")  # template generates items/X
        assert not template.matches_prefix("http://api.example.com/items/123/")  # template can't generate items/123/...

    def test_matches_prefix_longer_than_template(self):
        """Test that prefixes longer than template don't match."""

        def dummy_func(id: str) -> str:
            return f"Item {id}"

        template = ResourceTemplate.from_function(
            dummy_func, uri_template="http://api.example.com/items/{id}", name="test"
        )

        # Prefix has more segments than template
        assert not template.matches_prefix("http://api.example.com/items/123/extra/")
        assert not template.matches_prefix("http://api.example.com/items/123/extra/more/")
