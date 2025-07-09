from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

import annotated_types
import pytest
from dirty_equals import IsPartialDict
from pydantic import BaseModel, Field

from mcp.server.fastmcp.utilities.func_metadata import func_metadata


class SomeInputModelA(BaseModel):
    pass


class SomeInputModelB(BaseModel):
    class InnerModel(BaseModel):
        x: int

    how_many_shrimp: Annotated[int, Field(description="How many shrimp in the tank???")]
    ok: InnerModel
    y: None


def complex_arguments_fn(
    an_int: int,
    must_be_none: None,
    must_be_none_dumb_annotation: Annotated[None, "blah"],
    list_of_ints: list[int],
    # list[str] | str is an interesting case because if it comes in as JSON like
    # "[\"a\", \"b\"]" then it will be naively parsed as a string.
    list_str_or_str: list[str] | str,
    an_int_annotated_with_field: Annotated[int, Field(description="An int with a field")],
    an_int_annotated_with_field_and_others: Annotated[
        int,
        str,  # Should be ignored, really
        Field(description="An int with a field"),
        annotated_types.Gt(1),
    ],
    an_int_annotated_with_junk: Annotated[
        int,
        "123",
        456,
    ],
    field_with_default_via_field_annotation_before_nondefault_arg: Annotated[int, Field(1)],
    unannotated,
    my_model_a: SomeInputModelA,
    my_model_a_forward_ref: "SomeInputModelA",
    my_model_b: SomeInputModelB,
    an_int_annotated_with_field_default: Annotated[
        int,
        Field(1, description="An int with a field"),
    ],
    unannotated_with_default=5,
    my_model_a_with_default: SomeInputModelA = SomeInputModelA(),  # noqa: B008
    an_int_with_default: int = 1,
    must_be_none_with_default: None = None,
    an_int_with_equals_field: int = Field(1, ge=0),
    int_annotated_with_default: Annotated[int, Field(description="hey")] = 5,
) -> str:
    _ = (
        an_int,
        must_be_none,
        must_be_none_dumb_annotation,
        list_of_ints,
        list_str_or_str,
        an_int_annotated_with_field,
        an_int_annotated_with_field_and_others,
        an_int_annotated_with_junk,
        field_with_default_via_field_annotation_before_nondefault_arg,
        unannotated,
        an_int_annotated_with_field_default,
        unannotated_with_default,
        my_model_a,
        my_model_a_forward_ref,
        my_model_b,
        my_model_a_with_default,
        an_int_with_default,
        must_be_none_with_default,
        an_int_with_equals_field,
        int_annotated_with_default,
    )
    return "ok!"


@pytest.mark.anyio
async def test_complex_function_runtime_arg_validation_non_json():
    """Test that basic non-JSON arguments are validated correctly"""
    meta = func_metadata(complex_arguments_fn)

    # Test with minimum required arguments
    result = await meta.call_fn_with_arg_validation(
        complex_arguments_fn,
        fn_is_async=False,
        arguments_to_validate={
            "an_int": 1,
            "must_be_none": None,
            "must_be_none_dumb_annotation": None,
            "list_of_ints": [1, 2, 3],
            "list_str_or_str": "hello",
            "an_int_annotated_with_field": 42,
            "an_int_annotated_with_field_and_others": 5,
            "an_int_annotated_with_junk": 100,
            "unannotated": "test",
            "my_model_a": {},
            "my_model_a_forward_ref": {},
            "my_model_b": {"how_many_shrimp": 5, "ok": {"x": 1}, "y": None},
        },
        arguments_to_pass_directly=None,
    )
    assert result == "ok!"

    # Test with invalid types
    with pytest.raises(ValueError):
        await meta.call_fn_with_arg_validation(
            complex_arguments_fn,
            fn_is_async=False,
            arguments_to_validate={"an_int": "not an int"},
            arguments_to_pass_directly=None,
        )


@pytest.mark.anyio
async def test_complex_function_runtime_arg_validation_with_json():
    """Test that JSON string arguments are parsed and validated correctly"""
    meta = func_metadata(complex_arguments_fn)

    result = await meta.call_fn_with_arg_validation(
        complex_arguments_fn,
        fn_is_async=False,
        arguments_to_validate={
            "an_int": 1,
            "must_be_none": None,
            "must_be_none_dumb_annotation": None,
            "list_of_ints": "[1, 2, 3]",  # JSON string
            "list_str_or_str": '["a", "b", "c"]',  # JSON string
            "an_int_annotated_with_field": 42,
            "an_int_annotated_with_field_and_others": "5",  # JSON string
            "an_int_annotated_with_junk": 100,
            "unannotated": "test",
            "my_model_a": "{}",  # JSON string
            "my_model_a_forward_ref": "{}",  # JSON string
            "my_model_b": '{"how_many_shrimp": 5, "ok": {"x": 1}, "y": null}',
        },
        arguments_to_pass_directly=None,
    )
    assert result == "ok!"


def test_str_vs_list_str():
    """Test handling of string vs list[str] type annotations.

    This is tricky as '"hello"' can be parsed as a JSON string or a Python string.
    We want to make sure it's kept as a python string.
    """

    def func_with_str_types(str_or_list: str | list[str]):
        return str_or_list

    meta = func_metadata(func_with_str_types)

    # Test string input for union type
    result = meta.pre_parse_json({"str_or_list": "hello"})
    assert result["str_or_list"] == "hello"

    # Test string input that contains valid JSON for union type
    # We want to see here that the JSON-vali string is NOT parsed as JSON, but rather
    # kept as a raw string
    result = meta.pre_parse_json({"str_or_list": '"hello"'})
    assert result["str_or_list"] == '"hello"'

    # Test list input for union type
    result = meta.pre_parse_json({"str_or_list": '["hello", "world"]'})
    assert result["str_or_list"] == ["hello", "world"]


def test_skip_names():
    """Test that skipped parameters are not included in the model"""

    def func_with_many_params(keep_this: int, skip_this: str, also_keep: float, also_skip: bool):
        return keep_this, skip_this, also_keep, also_skip

    # Skip some parameters
    meta = func_metadata(func_with_many_params, skip_names=["skip_this", "also_skip"])

    # Check model fields
    assert "keep_this" in meta.arg_model.model_fields
    assert "also_keep" in meta.arg_model.model_fields
    assert "skip_this" not in meta.arg_model.model_fields
    assert "also_skip" not in meta.arg_model.model_fields

    # Validate that we can call with only non-skipped parameters
    model: BaseModel = meta.arg_model.model_validate({"keep_this": 1, "also_keep": 2.5})  # type: ignore
    assert model.keep_this == 1  # type: ignore
    assert model.also_keep == 2.5  # type: ignore


def test_structured_output_dict_str_types():
    """Test that dict[str, T] types are handled without wrapping."""

    # Test dict[str, Any]
    def func_dict_any() -> dict[str, Any]:
        return {"a": 1, "b": "hello", "c": [1, 2, 3]}

    meta = func_metadata(func_dict_any)

    assert meta.output_schema == IsPartialDict(type="object", title="func_dict_anyDictOutput")

    # Test dict[str, str]
    def func_dict_str() -> dict[str, str]:
        return {"name": "John", "city": "NYC"}

    meta = func_metadata(func_dict_str)
    assert meta.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "title": "func_dict_strDictOutput",
    }

    # Test dict[str, list[int]]
    def func_dict_list() -> dict[str, list[int]]:
        return {"nums": [1, 2, 3], "more": [4, 5, 6]}

    meta = func_metadata(func_dict_list)
    assert meta.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "integer"}},
        "title": "func_dict_listDictOutput",
    }

    # Test dict[int, str] - should be wrapped since key is not str
    def func_dict_int_key() -> dict[int, str]:
        return {1: "a", 2: "b"}

    meta = func_metadata(func_dict_int_key)
    assert meta.output_schema is not None
    assert "result" in meta.output_schema["properties"]


@pytest.mark.anyio
async def test_lambda_function():
    """Test lambda function schema and validation"""
    fn = lambda x, y=5: x  # noqa: E731
    meta = func_metadata(lambda x, y=5: x)

    # Test schema
    assert meta.arg_model.model_json_schema() == {
        "properties": {
            "x": {"title": "x", "type": "string"},
            "y": {"default": 5, "title": "y", "type": "string"},
        },
        "required": ["x"],
        "title": "<lambda>Arguments",
        "type": "object",
    }

    async def check_call(args):
        return await meta.call_fn_with_arg_validation(
            fn,
            fn_is_async=False,
            arguments_to_validate=args,
            arguments_to_pass_directly=None,
        )

    # Basic calls
    assert await check_call({"x": "hello"}) == "hello"
    assert await check_call({"x": "hello", "y": "world"}) == "hello"
    assert await check_call({"x": '"hello"'}) == '"hello"'

    # Missing required arg
    with pytest.raises(ValueError):
        await check_call({"y": "world"})


def test_complex_function_json_schema():
    """Test JSON schema generation for complex function arguments.

    Note: Different versions of pydantic output slightly different
    JSON Schema formats for model fields with defaults. The format changed in 2.9.0:

    1. Before 2.9.0:
       {
         "allOf": [{"$ref": "#/$defs/Model"}],
         "default": {}
       }

    2. Since 2.9.0:
       {
         "$ref": "#/$defs/Model",
         "default": {}
       }

    Both formats are valid and functionally equivalent. This test accepts either format
    to ensure compatibility across our supported pydantic versions.

    This change in format does not affect runtime behavior since:
    1. Both schemas validate the same way
    2. The actual model classes and validation logic are unchanged
    3. func_metadata uses model_validate/model_dump, not the schema directly
    """
    meta = func_metadata(complex_arguments_fn)
    actual_schema = meta.arg_model.model_json_schema()

    # Create a copy of the actual schema to normalize
    normalized_schema = actual_schema.copy()

    # Normalize the my_model_a_with_default field to handle both pydantic formats
    if "allOf" in actual_schema["properties"]["my_model_a_with_default"]:
        normalized_schema["properties"]["my_model_a_with_default"] = {
            "$ref": "#/$defs/SomeInputModelA",
            "default": {},
        }

    assert normalized_schema == {
        "$defs": {
            "InnerModel": {
                "properties": {"x": {"title": "X", "type": "integer"}},
                "required": ["x"],
                "title": "InnerModel",
                "type": "object",
            },
            "SomeInputModelA": {
                "properties": {},
                "title": "SomeInputModelA",
                "type": "object",
            },
            "SomeInputModelB": {
                "properties": {
                    "how_many_shrimp": {
                        "description": "How many shrimp in the tank???",
                        "title": "How Many Shrimp",
                        "type": "integer",
                    },
                    "ok": {"$ref": "#/$defs/InnerModel"},
                    "y": {"title": "Y", "type": "null"},
                },
                "required": ["how_many_shrimp", "ok", "y"],
                "title": "SomeInputModelB",
                "type": "object",
            },
        },
        "properties": {
            "an_int": {"title": "An Int", "type": "integer"},
            "must_be_none": {"title": "Must Be None", "type": "null"},
            "must_be_none_dumb_annotation": {
                "title": "Must Be None Dumb Annotation",
                "type": "null",
            },
            "list_of_ints": {
                "items": {"type": "integer"},
                "title": "List Of Ints",
                "type": "array",
            },
            "list_str_or_str": {
                "anyOf": [
                    {"items": {"type": "string"}, "type": "array"},
                    {"type": "string"},
                ],
                "title": "List Str Or Str",
            },
            "an_int_annotated_with_field": {
                "description": "An int with a field",
                "title": "An Int Annotated With Field",
                "type": "integer",
            },
            "an_int_annotated_with_field_and_others": {
                "description": "An int with a field",
                "exclusiveMinimum": 1,
                "title": "An Int Annotated With Field And Others",
                "type": "integer",
            },
            "an_int_annotated_with_junk": {
                "title": "An Int Annotated With Junk",
                "type": "integer",
            },
            "field_with_default_via_field_annotation_before_nondefault_arg": {
                "default": 1,
                "title": "Field With Default Via Field Annotation Before Nondefault Arg",
                "type": "integer",
            },
            "unannotated": {"title": "unannotated", "type": "string"},
            "my_model_a": {"$ref": "#/$defs/SomeInputModelA"},
            "my_model_a_forward_ref": {"$ref": "#/$defs/SomeInputModelA"},
            "my_model_b": {"$ref": "#/$defs/SomeInputModelB"},
            "an_int_annotated_with_field_default": {
                "default": 1,
                "description": "An int with a field",
                "title": "An Int Annotated With Field Default",
                "type": "integer",
            },
            "unannotated_with_default": {
                "default": 5,
                "title": "unannotated_with_default",
                "type": "string",
            },
            "my_model_a_with_default": {
                "$ref": "#/$defs/SomeInputModelA",
                "default": {},
            },
            "an_int_with_default": {
                "default": 1,
                "title": "An Int With Default",
                "type": "integer",
            },
            "must_be_none_with_default": {
                "default": None,
                "title": "Must Be None With Default",
                "type": "null",
            },
            "an_int_with_equals_field": {
                "default": 1,
                "minimum": 0,
                "title": "An Int With Equals Field",
                "type": "integer",
            },
            "int_annotated_with_default": {
                "default": 5,
                "description": "hey",
                "title": "Int Annotated With Default",
                "type": "integer",
            },
        },
        "required": [
            "an_int",
            "must_be_none",
            "must_be_none_dumb_annotation",
            "list_of_ints",
            "list_str_or_str",
            "an_int_annotated_with_field",
            "an_int_annotated_with_field_and_others",
            "an_int_annotated_with_junk",
            "unannotated",
            "my_model_a",
            "my_model_a_forward_ref",
            "my_model_b",
        ],
        "title": "complex_arguments_fnArguments",
        "type": "object",
    }


def test_str_vs_int():
    """
    Test that string values are kept as strings even when they contain numbers,
    while numbers are parsed correctly.
    """

    def func_with_str_and_int(a: str, b: int):
        return a

    meta = func_metadata(func_with_str_and_int)
    result = meta.pre_parse_json({"a": "123", "b": 123})
    assert result["a"] == "123"
    assert result["b"] == 123


# Tests for structured output functionality


def test_structured_output_requires_return_annotation():
    """Test that structured_output=True requires a return annotation"""
    from mcp.server.fastmcp.exceptions import InvalidSignature

    def func_no_annotation():
        return "hello"

    def func_none_annotation() -> None:
        return None

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_no_annotation, structured_output=True)
    assert "return annotation required" in str(exc_info.value)

    # None annotation should work
    meta = func_metadata(func_none_annotation)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "null"}},
        "required": ["result"],
        "title": "func_none_annotationOutput",
    }


def test_structured_output_basemodel():
    """Test structured output with BaseModel return types"""

    class PersonModel(BaseModel):
        name: str
        age: int
        email: str | None = None

    def func_returning_person() -> PersonModel:
        return PersonModel(name="Alice", age=30)

    meta = func_metadata(func_returning_person)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "age": {"title": "Age", "type": "integer"},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Email"},
        },
        "required": ["name", "age"],
        "title": "PersonModel",
    }


def test_structured_output_primitives():
    """Test structured output with primitive return types"""

    def func_str() -> str:
        return "hello"

    def func_int() -> int:
        return 42

    def func_float() -> float:
        return 3.14

    def func_bool() -> bool:
        return True

    def func_bytes() -> bytes:
        return b"data"

    # Test string
    meta = func_metadata(func_str)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "string"}},
        "required": ["result"],
        "title": "func_strOutput",
    }

    # Test int
    meta = func_metadata(func_int)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "integer"}},
        "required": ["result"],
        "title": "func_intOutput",
    }

    # Test float
    meta = func_metadata(func_float)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "number"}},
        "required": ["result"],
        "title": "func_floatOutput",
    }

    # Test bool
    meta = func_metadata(func_bool)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "boolean"}},
        "required": ["result"],
        "title": "func_boolOutput",
    }

    # Test bytes
    meta = func_metadata(func_bytes)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "string", "format": "binary"}},
        "required": ["result"],
        "title": "func_bytesOutput",
    }


def test_structured_output_generic_types():
    """Test structured output with generic types (list, dict, Union, etc.)"""

    def func_list_str() -> list[str]:
        return ["a", "b", "c"]

    def func_dict_str_int() -> dict[str, int]:
        return {"a": 1, "b": 2}

    def func_union() -> str | int:
        return "hello"

    def func_optional() -> str | None:
        return None

    # Test list
    meta = func_metadata(func_list_str)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "array", "items": {"type": "string"}}},
        "required": ["result"],
        "title": "func_list_strOutput",
    }

    # Test dict[str, int] - should NOT be wrapped
    meta = func_metadata(func_dict_str_int)
    assert meta.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
        "title": "func_dict_str_intDictOutput",
    }

    # Test Union
    meta = func_metadata(func_union)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "anyOf": [{"type": "string"}, {"type": "integer"}]}},
        "required": ["result"],
        "title": "func_unionOutput",
    }

    # Test Optional
    meta = func_metadata(func_optional)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["result"],
        "title": "func_optionalOutput",
    }


def test_structured_output_dataclass():
    """Test structured output with dataclass return types"""

    @dataclass
    class PersonDataClass:
        name: str
        age: int
        email: str | None = None
        tags: list[str] | None = None

    def func_returning_dataclass() -> PersonDataClass:
        return PersonDataClass(name="Bob", age=25)

    meta = func_metadata(func_returning_dataclass)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "age": {"title": "Age", "type": "integer"},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Email"},
            "tags": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Tags",
            },
        },
        "required": ["name", "age"],
        "title": "PersonDataClass",
    }


def test_structured_output_typeddict():
    """Test structured output with TypedDict return types"""

    class PersonTypedDictOptional(TypedDict, total=False):
        name: str
        age: int

    def func_returning_typeddict_optional() -> PersonTypedDictOptional:
        return {"name": "Dave"}  # Only returning one field to test partial dict

    meta = func_metadata(func_returning_typeddict_optional)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string", "default": None},
            "age": {"title": "Age", "type": "integer", "default": None},
        },
        "title": "PersonTypedDictOptional",
    }

    # Test with total=True (all required)
    class PersonTypedDictRequired(TypedDict):
        name: str
        age: int
        email: str | None

    def func_returning_typeddict_required() -> PersonTypedDictRequired:
        return {"name": "Eve", "age": 40, "email": None}  # Testing None value

    meta = func_metadata(func_returning_typeddict_required)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "age": {"title": "Age", "type": "integer"},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Email"},
        },
        "required": ["name", "age", "email"],
        "title": "PersonTypedDictRequired",
    }


def test_structured_output_ordinary_class():
    """Test structured output with ordinary annotated classes"""

    class PersonClass:
        name: str
        age: int
        email: str | None

        def __init__(self, name: str, age: int, email: str | None = None):
            self.name = name
            self.age = age
            self.email = email

    def func_returning_class() -> PersonClass:
        return PersonClass("Helen", 55)

    meta = func_metadata(func_returning_class)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "age": {"title": "Age", "type": "integer"},
            "email": {"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Email"},
        },
        "required": ["name", "age", "email"],
        "title": "PersonClass",
    }


def test_unstructured_output_unannotated_class():
    # Test with class that has no annotations
    class UnannotatedClass:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    def func_returning_unannotated() -> UnannotatedClass:
        return UnannotatedClass(1, 2)

    meta = func_metadata(func_returning_unannotated)
    assert meta.output_schema is None


def test_structured_output_with_field_descriptions():
    """Test that Field descriptions are preserved in structured output"""

    class ModelWithDescriptions(BaseModel):
        name: Annotated[str, Field(description="The person's full name")]
        age: Annotated[int, Field(description="Age in years", ge=0, le=150)]

    def func_with_descriptions() -> ModelWithDescriptions:
        return ModelWithDescriptions(name="Ian", age=60)

    meta = func_metadata(func_with_descriptions)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string", "description": "The person's full name"},
            "age": {"title": "Age", "type": "integer", "description": "Age in years", "minimum": 0, "maximum": 150},
        },
        "required": ["name", "age"],
        "title": "ModelWithDescriptions",
    }


def test_structured_output_nested_models():
    """Test structured output with nested models"""

    class Address(BaseModel):
        street: str
        city: str
        zipcode: str

    class PersonWithAddress(BaseModel):
        name: str
        address: Address

    def func_nested() -> PersonWithAddress:
        return PersonWithAddress(name="Jack", address=Address(street="123 Main St", city="Anytown", zipcode="12345"))

    meta = func_metadata(func_nested)
    assert meta.output_schema == {
        "type": "object",
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {
                    "street": {"title": "Street", "type": "string"},
                    "city": {"title": "City", "type": "string"},
                    "zipcode": {"title": "Zipcode", "type": "string"},
                },
                "required": ["street", "city", "zipcode"],
                "title": "Address",
            }
        },
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "address": {"$ref": "#/$defs/Address"},
        },
        "required": ["name", "address"],
        "title": "PersonWithAddress",
    }


def test_structured_output_unserializable_type_error():
    """Test error when structured_output=True is used with unserializable types"""
    from typing import NamedTuple

    from mcp.server.fastmcp.exceptions import InvalidSignature

    # Test with a class that has non-serializable default values
    class ConfigWithCallable:
        name: str
        # Callable defaults are not JSON serializable and will trigger Pydantic warnings
        callback: Any = lambda x: x * 2

    def func_returning_config_with_callable() -> ConfigWithCallable:
        return ConfigWithCallable()

    # Should work without structured_output=True (returns None for output_schema)
    meta = func_metadata(func_returning_config_with_callable)
    assert meta.output_schema is None

    # Should raise error with structured_output=True
    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_returning_config_with_callable, structured_output=True)
    assert "is not serializable for structured output" in str(exc_info.value)
    assert "ConfigWithCallable" in str(exc_info.value)

    # Also test with NamedTuple for good measure
    class Point(NamedTuple):
        x: int
        y: int

    def func_returning_namedtuple() -> Point:
        return Point(1, 2)

    # Should work without structured_output=True (returns None for output_schema)
    meta = func_metadata(func_returning_namedtuple)
    assert meta.output_schema is None

    # Should raise error with structured_output=True
    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_returning_namedtuple, structured_output=True)
    assert "is not serializable for structured output" in str(exc_info.value)
    assert "Point" in str(exc_info.value)


def test_structured_output_aliases():
    """Test that field aliases are consistent between schema and output"""

    class ModelWithAliases(BaseModel):
        field_first: str | None = Field(default=None, alias="first", description="The first field.")
        field_second: str | None = Field(default=None, alias="second", description="The second field.")

    def func_with_aliases() -> ModelWithAliases:
        # When aliases are defined, we must use the aliased names to set values
        return ModelWithAliases(**{"first": "hello", "second": "world"})

    meta = func_metadata(func_with_aliases)

    # Check that schema uses aliases
    assert meta.output_schema is not None
    assert "first" in meta.output_schema["properties"]
    assert "second" in meta.output_schema["properties"]
    assert "field_first" not in meta.output_schema["properties"]
    assert "field_second" not in meta.output_schema["properties"]

    # Check that the actual output uses aliases too
    result = ModelWithAliases(**{"first": "hello", "second": "world"})
    unstructured_content, structured_content = meta.convert_result(result)

    # The structured content should use aliases to match the schema
    assert "first" in structured_content
    assert "second" in structured_content
    assert "field_first" not in structured_content
    assert "field_second" not in structured_content
    assert structured_content["first"] == "hello"
    assert structured_content["second"] == "world"

    # Also test the case where we have a model with defaults to ensure aliases work in all cases
    result_with_defaults = ModelWithAliases()  # Uses default None values
    unstructured_content_defaults, structured_content_defaults = meta.convert_result(result_with_defaults)

    # Even with defaults, should use aliases in output
    assert "first" in structured_content_defaults
    assert "second" in structured_content_defaults
    assert "field_first" not in structured_content_defaults
    assert "field_second" not in structured_content_defaults
    assert structured_content_defaults["first"] is None
    assert structured_content_defaults["second"] is None
