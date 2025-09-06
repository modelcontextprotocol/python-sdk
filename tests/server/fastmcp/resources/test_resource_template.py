import json
from typing import Any

import pytest
from pydantic import BaseModel

from mcp.server.fastmcp.resources import FunctionResource, ResourceTemplate


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

    def test_template_with_optional_parameters(self):
        """Test templates with optional parameters via query string."""

        def my_func(key: str, sort: str = "asc", limit: int = 10) -> dict[str, str | int]:
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
            match="Mismatch between URI path parameters .* and required function parameters .*",
        ):
            ResourceTemplate.from_function(
                fn=invalid_func,
                uri_template="test://{key}",
                name="test",
            )

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

    @pytest.mark.anyio
    async def test_create_resource_with_optional_params(self):
        """Test creating resources with optional parameters."""

        def my_func(key: str, sort: str = "asc", limit: int = 10) -> dict[str, str | int]:
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
        resource = await template.create_resource("test://foo?sort=desc&limit=20", params)
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
        ) -> dict[str, str | int]:
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
        params = template.matches("test://electronics/1234?filter=new&sort=price&limit=20")
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
        def valid_func(key: str, opt1: str = "default", opt2: int = 10, opt3: bool = False) -> str:
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
            match="Mismatch between URI path parameters .* and required function parameters .*",
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
        ) -> dict[str, str | int]:
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

        # Create with all params (limit will be string "20",Pydantic handles conversion)
        uri = "items://electronics/1234?filter=new&sort=price&limit=20"
        params = {
            "category": "electronics",
            "id": "1234",
            "filter": "new",
            "sort": "price",
            "limit": "20",  # value from URI is a string
        }
        resource = await template.create_resource(uri, params)
        result = await resource.read()
        assert isinstance(result, str)
        assert json.loads(result) == {
            "category": "electronics",
            "id": "1234",
            "filter": "new",
            "sort": "price",
            "limit": 20,  # Pydantic converted "20" to 20
        }

    @pytest.mark.anyio
    async def test_create_resource_optional_param_validation_fallback(self):
        """
        Test that if optional parameters fail Pydantic validation,
        their default values are used due to the
        use_defaults_on_optional_validation_error decorator.
        """

        def func_with_optional_typed_params(
            key: str, opt_int: int = 42, opt_bool: bool = True
        ) -> dict[str, str | int | bool]:
            return {"key": key, "opt_int": opt_int, "opt_bool": opt_bool}

        template = ResourceTemplate.from_function(
            fn=func_with_optional_typed_params,
            uri_template="test://{key}{?opt_int,opt_bool}",
            name="test_optional_fallback",
        )

        # Case 1: opt_int is invalid, opt_bool is not provided
        # URI like "test://mykey?opt_int=notanint"
        params_invalid_int = {"key": "mykey", "opt_int": "notanint"}
        resource1 = await template.create_resource("test://mykey?opt_int=notanint", params_invalid_int)
        result1_str = await resource1.read()
        result1 = json.loads(result1_str)
        assert result1["key"] == "mykey"
        assert result1["opt_int"] == 42  # Default used
        assert result1["opt_bool"] is True  # Default used

        # Case 2: opt_bool is invalid, opt_int is valid
        # URI like "test://mykey?opt_int=100&opt_bool=notabool"
        params_invalid_bool = {
            "key": "mykey",
            "opt_int": "100",  # Valid string for int
            "opt_bool": "notabool",
        }
        resource2 = await template.create_resource("test://mykey?opt_int=100&opt_bool=notabool", params_invalid_bool)
        result2_str = await resource2.read()
        result2 = json.loads(result2_str)
        assert result2["key"] == "mykey"
        assert result2["opt_int"] == 100  # Provided valid value used
        assert result2["opt_bool"] is True  # Default used

        # Case 3: Both opt_int and opt_bool are invalid
        # URI like "test://mykey?opt_int=bad&opt_bool=bad"
        params_both_invalid = {
            "key": "mykey",
            "opt_int": "bad",
            "opt_bool": "bad",
        }
        resource3 = await template.create_resource("test://mykey?opt_int=bad&opt_bool=bad", params_both_invalid)
        result3_str = await resource3.read()
        result3 = json.loads(result3_str)
        assert result3["key"] == "mykey"
        assert result3["opt_int"] == 42  # Default used
        assert result3["opt_bool"] is True  # Default used

        # Case 4: Empty value for opt_int (should fall back to default)
        # URI like "test://mykey?opt_int="
        params_empty_int = {"key": "mykey"}
        resource4 = await template.create_resource("test://mykey?opt_int=", params_empty_int)
        result4_str = await resource4.read()
        result4 = json.loads(result4_str)
        assert result4["key"] == "mykey"
        assert result4["opt_int"] == 42  # Default used
        assert result4["opt_bool"] is True  # Default used

        # Case 5: Empty value for opt_bool (should fall back to default)
        # URI like "test://mykey?opt_bool="
        params_empty_bool = {"key": "mykey"}
        resource5 = await template.create_resource("test://mykey?opt_bool=", params_empty_bool)
        result5_str = await resource5.read()
        result5 = json.loads(result5_str)
        assert result5["key"] == "mykey"
        assert result5["opt_int"] == 42  # Default used
        assert result5["opt_bool"] is True  # Default used

        # Case 6: Optional string param with empty value, should use default value
        def func_opt_str(key: str, opt_s: str = "default_val") -> dict[str, str]:
            return {"key": key, "opt_s": opt_s}

        template_str = ResourceTemplate.from_function(
            fn=func_opt_str, uri_template="test://{key}{?opt_s}", name="test_opt_str"
        )
        params_empty_str = {"key": "mykey"}
        resource6 = await template_str.create_resource("test://mykey?opt_s=", params_empty_str)
        result6_str = await resource6.read()
        result6 = json.loads(result6_str)
        assert result6["key"] == "mykey"
        assert result6["opt_s"] == "default_val"  # Pydantic allows empty string for str type

    @pytest.mark.anyio
    async def test_create_resource_required_param_validation_error(self):
        """
        Test that if a required parameter fails Pydantic validation, an error is raised
        and not suppressed by the new decorator.
        """

        def func_with_required_typed_param(req_int: int, key: str) -> dict[str, int | str]:
            return {"req_int": req_int, "key": key}

        template = ResourceTemplate.from_function(
            fn=func_with_required_typed_param,
            uri_template="test://{key}/{req_int}",  # req_int is part of path
            name="test_req_error",
        )

        # req_int is "notanint", which is invalid for int type
        params_invalid_req = {"key": "mykey", "req_int": "notanint"}
        with pytest.raises(ValueError, match="Error creating resource from template"):
            # This ValueError comes from ResourceTemplate.create_resource own try-except
            # which catches Pydantic's ValidationError.
            await template.create_resource("test://mykey/notanint", params_invalid_req)
