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
        assert content == "hello"

    def test_context_parameter_detection(self):
        """Test that context params are detected in ResourceTemplate.from_function()."""
        from mcp.server.fastmcp import Context

        def resource_with_context(key: str, ctx: Context) -> str:
            return f"Key: {key}"

        template = ResourceTemplate.from_function(
            fn=resource_with_context,
            uri_template="test://{key}",
            name="test",
        )
        assert template.context_kwarg == "ctx"

        def resource_without_context(key: str) -> str:
            return f"Key: {key}"

        template = ResourceTemplate.from_function(
            fn=resource_without_context,
            uri_template="test://{key}",
            name="test",
        )
        assert template.context_kwarg is None

    @pytest.mark.anyio
    async def test_context_injection(self):
        """Test that context is properly injected during resource creation."""
        from mcp.server.fastmcp import Context, FastMCP

        def resource_with_context(key: str, ctx: Context) -> str:
            assert isinstance(ctx, Context)
            return f"Key: {key}"

        template = ResourceTemplate.from_function(
            fn=resource_with_context,
            uri_template="test://{key}",
            name="test",
        )

        mcp = FastMCP()
        ctx = mcp.get_context()
        resource = await template.create_resource(
            "test://value", {"key": "value"}, context=ctx
        )
        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Key: value"

    @pytest.mark.anyio
    async def test_context_injection_async(self):
        """Test that context is properly injected in async resource functions."""
        from mcp.server.fastmcp import Context, FastMCP

        async def async_resource(key: str, ctx: Context) -> str:
            assert isinstance(ctx, Context)
            return f"Async Key: {key}"

        template = ResourceTemplate.from_function(
            fn=async_resource,
            uri_template="test://{key}",
            name="test",
        )

        mcp = FastMCP()
        ctx = mcp.get_context()
        resource = await template.create_resource(
            "test://value", {"key": "value"}, context=ctx
        )
        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Async Key: value"

    @pytest.mark.anyio
    async def test_context_optional(self):
        """Test that context is optional when creating resources."""
        from mcp.server.fastmcp import Context

        def resource_with_optional_context(key: str, ctx: Context | None = None) -> str:
            return f"Key: {key}"

        template = ResourceTemplate.from_function(
            fn=resource_with_optional_context,
            uri_template="test://{key}",
            name="test",
        )

        resource = await template.create_resource("test://value", {"key": "value"})
        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Key: value"

    @pytest.mark.anyio
    async def test_context_error_handling(self):
        """Test error handling when context injection fails."""
        from mcp.server.fastmcp import Context, FastMCP

        def resource_with_context(key: str, ctx: Context) -> str:
            raise ValueError("Test error")

        template = ResourceTemplate.from_function(
            fn=resource_with_context,
            uri_template="test://{key}",
            name="test",
        )

        mcp = FastMCP()
        ctx = mcp.get_context()
        with pytest.raises(ValueError, match="Error creating resource from template"):
            await template.create_resource(
                "test://value", {"key": "value"}, context=ctx
            )

    def test_context_arg_excluded_from_schema(self):
        """Test that context parameters are excluded from the JSON schema."""
        from mcp.server.fastmcp import Context

        def resource_with_context(a: str, ctx: Context) -> str:
            return a

        template = ResourceTemplate.from_function(
            fn=resource_with_context,
            uri_template="test://{key}",
            name="test",
        )

        assert "ctx" not in json.dumps(template.parameters)
        assert "Context" not in json.dumps(template.parameters)
