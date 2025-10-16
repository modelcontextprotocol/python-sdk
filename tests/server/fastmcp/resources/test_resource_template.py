import json
from typing import Any

import pytest
from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource, ResourceTemplate
from mcp.types import Annotations


class TestResourceTemplate:
    """Test ResourceTemplate functionality."""

    def test_template_creation(self):
        """Test creating a template from a function."""

        def my_func(key: str, value: int) -> dict[str, Any]:
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )
        assert template.uri_template == "test://{key}/{value}"
        assert template.name == "test"
        assert template.mime_type == "text/plain"  # default
        assert template.fn(key="test", value=42) == my_func(key="test", value=42)

    def test_template_matches(self):
        """Test matching URIs against a template."""

        def my_func(key: str, value: int) -> dict[str, Any]:
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

        def my_func(key: str, value: int) -> dict[str, Any]:
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


class TestResourceTemplateAnnotations:
    """Test annotations on resource templates."""

    def test_template_with_annotations(self):
        """Test creating a template with annotations."""

        def get_user_data(user_id: str) -> str:
            return f"User {user_id}"

        annotations = Annotations(priority=0.9)

        template = ResourceTemplate.from_function(
            fn=get_user_data, uri_template="resource://users/{user_id}", annotations=annotations
        )

        assert template.annotations is not None
        assert template.annotations.priority == 0.9

    def test_template_without_annotations(self):
        """Test that annotations are optional for templates."""

        def get_user_data(user_id: str) -> str:
            return f"User {user_id}"

        template = ResourceTemplate.from_function(fn=get_user_data, uri_template="resource://users/{user_id}")

        assert template.annotations is None

    @pytest.mark.anyio
    async def test_template_annotations_in_fastmcp(self):
        """Test template annotations via FastMCP decorator."""

        mcp = FastMCP()

        @mcp.resource("resource://dynamic/{id}", annotations=Annotations(audience=["user"], priority=0.7))
        def get_dynamic(id: str) -> str:
            """A dynamic annotated resource."""
            return f"Data for {id}"

        templates = await mcp.list_resource_templates()
        assert len(templates) == 1
        assert templates[0].annotations is not None
        assert templates[0].annotations.audience == ["user"]
        assert templates[0].annotations.priority == 0.7

    @pytest.mark.anyio
    async def test_template_created_resources_inherit_annotations(self):
        """Test that resources created from templates inherit annotations."""

        def get_item(item_id: str) -> str:
            return f"Item {item_id}"

        annotations = Annotations(priority=0.6)

        template = ResourceTemplate.from_function(
            fn=get_item, uri_template="resource://items/{item_id}", annotations=annotations
        )

        # Create a resource from the template
        resource = await template.create_resource("resource://items/123", {"item_id": "123"})

        # The resource should inherit the template's annotations
        assert resource.annotations is not None
        assert resource.annotations.priority == 0.6

        # Verify the resource works correctly
        content = await resource.read()
        assert content == "Item 123"
