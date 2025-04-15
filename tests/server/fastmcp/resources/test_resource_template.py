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

    def test_template_with_optional_parameters(self):
        """Test templates with optional parameters via query string."""

        def my_func(key: str, sort: str = "asc", limit: int = 10) -> dict:
            return {"key": key, "sort": sort, "limit": limit}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}",
            name="test",
        )

        # Verify required/optional params
        assert template.required_params == {"key"}
        assert template.optional_params == {"sort", "limit"}

        # Match with no query params - should only extract path param
        params = template.matches("test://foo")
        assert params == {"key": "foo"}

        # Match with query params
        params = template.matches("test://foo?sort=desc&limit=20")
        assert params == {"key": "foo", "sort": "desc", "limit": "20"}

        # Match with partial query params
        params = template.matches("test://foo?sort=desc")
        assert params == {"key": "foo", "sort": "desc"}

        # Match with unknown query params - should ignore
        params = template.matches("test://foo?unknown=value")
        assert params == {"key": "foo"}

    def test_template_validation(self):
        """Test template validation with required/optional parameters."""

        # Valid: required param in path
        def valid_func(key: str, optional: str = "default") -> str:
            return f"{key}-{optional}"

        template = ResourceTemplate.from_function(
            fn=valid_func,
            uri_template="test://{key}",
            name="test",
        )
        assert template.required_params == {"key"}
        assert template.optional_params == {"optional"}

        # Invalid: missing required param in path
        def invalid_func(key: str, value: str) -> str:
            return f"{key}-{value}"

        with pytest.raises(
            ValueError,
            match="Mismatch between URI path parameters .* and "
            "required function parameters .*",
        ):
            ResourceTemplate.from_function(
                fn=invalid_func,
                uri_template="test://{key}",
                name="test",
            )

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

    @pytest.mark.anyio
    async def test_create_resource_with_optional_params(self):
        """Test creating resources with optional parameters."""

        def my_func(key: str, sort: str = "asc", limit: int = 10) -> dict:
            return {"key": key, "sort": sort, "limit": limit}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}",
            name="test",
        )

        # Create with only required params
        params = {"key": "foo"}
        resource = await template.create_resource("test://foo", params)
        result = await resource.read()
        assert isinstance(result, str)
        assert json.loads(result) == {"key": "foo", "sort": "asc", "limit": 10}

        # Create with all params
        params = {"key": "foo", "sort": "desc", "limit": "20"}
        resource = await template.create_resource(
            "test://foo?sort=desc&limit=20", params
        )
        result = await resource.read()
        assert isinstance(result, str)
        assert json.loads(result) == {"key": "foo", "sort": "desc", "limit": 20}

    def test_template_with_form_style_query_expansion(self):
        """Test templates with RFC 6570 form-style query expansion."""

        def my_func(
            category: str,
            id: str,
            filter: str = "all",
            sort: str = "name",
            limit: int = 10,
        ) -> dict:
            return {
                "category": category,
                "id": id,
                "filter": filter,
                "sort": sort,
                "limit": limit,
            }

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{category}/{id}{?filter,sort,limit}",
            name="test",
        )

        # Verify required/optional params
        assert template.required_params == {"category", "id"}
        assert template.optional_params == {"filter", "sort", "limit"}

        # Match with no query params - should only extract path params
        params = template.matches("test://electronics/1234")
        assert params == {"category": "electronics", "id": "1234"}

        # Match with all query params
        params = template.matches(
            "test://electronics/1234?filter=new&sort=price&limit=20"
        )
        assert params == {
            "category": "electronics",
            "id": "1234",
            "filter": "new",
            "sort": "price",
            "limit": "20",
        }

        # Match with partial query params
        params = template.matches("test://electronics/1234?filter=new&sort=price")
        assert params == {
            "category": "electronics",
            "id": "1234",
            "filter": "new",
            "sort": "price",
        }

        # Match with unknown query params - should ignore
        params = template.matches("test://electronics/1234?filter=new&unknown=value")
        assert params == {"category": "electronics", "id": "1234", "filter": "new"}

    def test_form_style_query_validation(self):
        """Test validation of form-style query parameters."""

        # Valid: query params are subset of optional params
        def valid_func(
            key: str, opt1: str = "default", opt2: int = 10, opt3: bool = False
        ) -> str:
            return f"{key}-{opt1}-{opt2}-{opt3}"

        template = ResourceTemplate.from_function(
            fn=valid_func,
            uri_template="test://{key}{?opt1,opt2}",
            name="test",
        )
        assert template.required_params == {"key"}
        assert template.optional_params == {"opt1", "opt2", "opt3"}

        # Invalid: query param not optional in function
        def invalid_func(key: str, required: str) -> str:
            return f"{key}-{required}"

        with pytest.raises(
            ValueError,
            match="Mismatch between URI path parameters .* and "
            "required function parameters .*",
        ):
            ResourceTemplate.from_function(
                fn=invalid_func,
                uri_template="test://{key}{?required}",
                name="test",
            )

    @pytest.mark.anyio
    async def test_create_resource_with_form_style_query(self):
        """Test creating resources with form-style query parameters."""

        def item_func(
            category: str,
            id: str,
            filter: str = "all",
            sort: str = "name",
            limit: int = 10,
        ) -> dict:
            return {
                "category": category,
                "id": id,
                "filter": filter,
                "sort": sort,
                "limit": limit,
            }

        template = ResourceTemplate.from_function(
            fn=item_func,
            uri_template="items://{category}/{id}{?filter,sort,limit}",
            name="item",
        )

        # Create with only required params
        params = {"category": "electronics", "id": "1234"}
        resource = await template.create_resource("items://electronics/1234", params)
        result = await resource.read()
        assert isinstance(result, str)
        assert json.loads(result) == {
            "category": "electronics",
            "id": "1234",
            "filter": "all",
            "sort": "name",
            "limit": 10,
        }

        # Create with all params
        uri = "items://electronics/1234?filter=new&sort=price&limit=20"
        params = {
            "category": "electronics",
            "id": "1234",
            "filter": "new",
            "sort": "price",
            "limit": "20",
        }
        resource = await template.create_resource(uri, params)
        result = await resource.read()
        assert isinstance(result, str)
        assert json.loads(result) == {
            "category": "electronics",
            "id": "1234",
            "filter": "new",
            "sort": "price",
            "limit": 20,
        }
