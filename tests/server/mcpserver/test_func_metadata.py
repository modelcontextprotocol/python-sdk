# Suppressed because these tests deliberately use wrong/missing type annotations.
# pyright: reportUnknownParameterType=false
# pyright: reportMissingParameterType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Final, NamedTuple, TypedDict

import annotated_types
import pytest
from dirty_equals import IsPartialDict
from mcp_types import CallToolResult, InputRequiredResult
from pydantic import BaseModel, Field

from mcp.server.mcpserver.exceptions import InvalidSignature
from mcp.server.mcpserver.utilities.func_metadata import func_metadata


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
    # JSON input like "[\"a\", \"b\"]" would be naively parsed as a string here
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
    _: Any = (
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
    meta = func_metadata(complex_arguments_fn)

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

    with pytest.raises(ValueError):
        await meta.call_fn_with_arg_validation(
            complex_arguments_fn,
            fn_is_async=False,
            arguments_to_validate={"an_int": "not an int"},
            arguments_to_pass_directly=None,
        )


@pytest.mark.anyio
async def test_complex_function_runtime_arg_validation_with_json():
    meta = func_metadata(complex_arguments_fn)

    result = await meta.call_fn_with_arg_validation(
        complex_arguments_fn,
        fn_is_async=False,
        arguments_to_validate={
            "an_int": 1,
            "must_be_none": None,
            "must_be_none_dumb_annotation": None,
            "list_of_ints": "[1, 2, 3]",
            "list_str_or_str": '["a", "b", "c"]',
            "an_int_annotated_with_field": 42,
            "an_int_annotated_with_field_and_others": "5",
            "an_int_annotated_with_junk": 100,
            "unannotated": "test",
            "my_model_a": "{}",
            "my_model_a_forward_ref": "{}",
            "my_model_b": '{"how_many_shrimp": 5, "ok": {"x": 1}, "y": null}',
        },
        arguments_to_pass_directly=None,
    )
    assert result == "ok!"


@pytest.mark.anyio
async def test_call_fn_does_not_mutate_pre_validated():
    def fn(x: int, ctx: str) -> str:
        return f"{x}:{ctx}"

    meta = func_metadata(fn, skip_names=["ctx"])
    pre_validated = meta.validate_arguments({"x": 1})
    snapshot = dict(pre_validated)

    result = await meta.call_fn_with_arg_validation(
        fn,
        fn_is_async=False,
        arguments_to_validate={"x": 1},
        arguments_to_pass_directly={"ctx": "injected"},
        pre_validated=pre_validated,
    )
    assert result == "1:injected"
    assert pre_validated == snapshot  # `ctx` was not leaked into the caller's dict


def test_str_vs_list_str():
    """A JSON-valid string like '"hello"' must be kept as a raw Python string, not parsed as JSON."""

    def func_with_str_types(str_or_list: str | list[str]):  # pragma: no cover
        return str_or_list

    meta = func_metadata(func_with_str_types)

    result = meta.pre_parse_json({"str_or_list": "hello"})
    assert result["str_or_list"] == "hello"

    result = meta.pre_parse_json({"str_or_list": '"hello"'})
    assert result["str_or_list"] == '"hello"'

    result = meta.pre_parse_json({"str_or_list": '["hello", "world"]'})
    assert result["str_or_list"] == ["hello", "world"]


def test_skip_names():
    def func_with_many_params(keep_this: int, skip_this: str, also_keep: float, also_skip: bool):  # pragma: no cover
        return keep_this, skip_this, also_keep, also_skip

    meta = func_metadata(func_with_many_params, skip_names=["skip_this", "also_skip"])

    assert "keep_this" in meta.arg_model.model_fields
    assert "also_keep" in meta.arg_model.model_fields
    assert "skip_this" not in meta.arg_model.model_fields
    assert "also_skip" not in meta.arg_model.model_fields

    model: BaseModel = meta.arg_model.model_validate({"keep_this": 1, "also_keep": 2.5})  # type: ignore
    assert model.keep_this == 1  # type: ignore
    assert model.also_keep == 2.5  # type: ignore


def test_structured_output_dict_str_types():
    """Test that dict[str, T] types are handled without wrapping."""

    def func_dict_any() -> dict[str, Any]:  # pragma: no cover
        return {"a": 1, "b": "hello", "c": [1, 2, 3]}

    meta = func_metadata(func_dict_any)

    assert meta.output_schema == IsPartialDict(type="object", title="func_dict_anyDictOutput")

    def func_dict_str() -> dict[str, str]:  # pragma: no cover
        return {"name": "John", "city": "NYC"}

    meta = func_metadata(func_dict_str)
    assert meta.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "title": "func_dict_strDictOutput",
    }

    def func_dict_list() -> dict[str, list[int]]:  # pragma: no cover
        return {"nums": [1, 2, 3], "more": [4, 5, 6]}

    meta = func_metadata(func_dict_list)
    assert meta.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "array", "items": {"type": "integer"}},
        "title": "func_dict_listDictOutput",
    }

    # dict[int, str] is wrapped since the key is not str
    def func_dict_int_key() -> dict[int, str]:  # pragma: no cover
        return {1: "a", 2: "b"}

    meta = func_metadata(func_dict_int_key)
    assert meta.output_schema is not None
    assert "result" in meta.output_schema["properties"]


@pytest.mark.anyio
async def test_lambda_function():
    fn: Callable[[str, int], str] = lambda x, y=5: x  # noqa: E731
    meta = func_metadata(lambda x, y=5: x)

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

    assert await check_call({"x": "hello"}) == "hello"
    assert await check_call({"x": "hello", "y": "world"}) == "hello"
    assert await check_call({"x": '"hello"'}) == '"hello"'

    with pytest.raises(ValueError):
        await check_call({"y": "world"})


def test_complex_function_json_schema():
    meta = func_metadata(complex_arguments_fn)
    actual_schema = meta.arg_model.model_json_schema()

    normalized_schema = actual_schema.copy()

    # pydantic <2.9 emits {"allOf": [{"$ref": ...}], "default": ...} for model fields with
    # defaults; >=2.9 inlines the $ref. Normalize to the >=2.9 form so either passes.
    if "allOf" in actual_schema["properties"]["my_model_a_with_default"]:  # pragma: no cover
        normalized_schema["properties"]["my_model_a_with_default"] = {  # pragma: no cover
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
    """Numeric-looking string values stay strings."""

    def func_with_str_and_int(a: str, b: int):  # pragma: no cover
        return a

    meta = func_metadata(func_with_str_and_int)
    result = meta.pre_parse_json({"a": "123", "b": 123})
    assert result["a"] == "123"
    assert result["b"] == 123


def test_str_annotation_preserves_json_string():
    """Regression test for PR #1113: params annotated as str keep valid-JSON strings as strings."""

    def process_json_config(config: str, enabled: bool = True) -> str:  # pragma: no cover
        return f"Processing config: {config}"

    meta = func_metadata(process_json_config)

    json_obj_str = '{"database": "postgres", "port": 5432}'
    result = meta.pre_parse_json({"config": json_obj_str, "enabled": True})

    assert isinstance(result["config"], str)
    assert result["config"] == json_obj_str

    json_array_str = '["item1", "item2", "item3"]'
    result = meta.pre_parse_json({"config": json_array_str})

    assert isinstance(result["config"], str)
    assert result["config"] == json_array_str

    json_string_str = '"This is a JSON string"'
    result = meta.pre_parse_json({"config": json_string_str})

    assert isinstance(result["config"], str)
    assert result["config"] == json_string_str

    complex_json_str = '{"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}], "count": 2}'
    result = meta.pre_parse_json({"config": complex_json_str})

    assert isinstance(result["config"], str)
    assert result["config"] == complex_json_str


@pytest.mark.anyio
async def test_str_annotation_runtime_validation():
    """Regression test for PR #1113: runtime validation passes JSON-bearing str params through unchanged."""

    def handle_json_payload(payload: str, strict_mode: bool = False) -> str:
        assert isinstance(payload, str), f"Expected str, got {type(payload)}"
        return f"Handled payload of length {len(payload)}"

    meta = func_metadata(handle_json_payload)

    json_payload = '{"action": "create", "resource": "user", "data": {"name": "Test User"}}'

    result = await meta.call_fn_with_arg_validation(
        handle_json_payload,
        fn_is_async=False,
        arguments_to_validate={"payload": json_payload, "strict_mode": True},
        arguments_to_pass_directly=None,
    )

    assert result == f"Handled payload of length {len(json_payload)}"

    json_array_payload = '["task1", "task2", "task3"]'

    result = await meta.call_fn_with_arg_validation(
        handle_json_payload,
        fn_is_async=False,
        arguments_to_validate={"payload": json_array_payload},
        arguments_to_pass_directly=None,
    )

    assert result == f"Handled payload of length {len(json_array_payload)}"


def test_structured_output_requires_return_annotation():
    def func_no_annotation():  # pragma: no cover
        return "hello"

    def func_none_annotation() -> None:  # pragma: no cover
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
    class PersonModel(BaseModel):
        name: str
        age: int
        email: str | None = None

    def func_returning_person() -> PersonModel:  # pragma: no cover
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
    def func_str() -> str:  # pragma: no cover
        return "hello"

    def func_int() -> int:  # pragma: no cover
        return 42

    def func_float() -> float:  # pragma: no cover
        return 3.14

    def func_bool() -> bool:  # pragma: no cover
        return True

    def func_bytes() -> bytes:  # pragma: no cover
        return b"data"

    meta = func_metadata(func_str)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "string"}},
        "required": ["result"],
        "title": "func_strOutput",
    }

    meta = func_metadata(func_int)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "integer"}},
        "required": ["result"],
        "title": "func_intOutput",
    }

    meta = func_metadata(func_float)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "number"}},
        "required": ["result"],
        "title": "func_floatOutput",
    }

    meta = func_metadata(func_bool)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "boolean"}},
        "required": ["result"],
        "title": "func_boolOutput",
    }

    meta = func_metadata(func_bytes)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "string", "format": "binary"}},
        "required": ["result"],
        "title": "func_bytesOutput",
    }


def test_structured_output_generic_types():
    def func_list_str() -> list[str]:  # pragma: no cover
        return ["a", "b", "c"]

    def func_dict_str_int() -> dict[str, int]:  # pragma: no cover
        return {"a": 1, "b": 2}

    def func_union() -> str | int:  # pragma: no cover
        return "hello"

    def func_optional() -> str | None:  # pragma: no cover
        return None

    meta = func_metadata(func_list_str)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "type": "array", "items": {"type": "string"}}},
        "required": ["result"],
        "title": "func_list_strOutput",
    }

    # dict[str, int] is NOT wrapped
    meta = func_metadata(func_dict_str_int)
    assert meta.output_schema == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
        "title": "func_dict_str_intDictOutput",
    }

    meta = func_metadata(func_union)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "anyOf": [{"type": "string"}, {"type": "integer"}]}},
        "required": ["result"],
        "title": "func_unionOutput",
    }

    meta = func_metadata(func_optional)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"title": "Result", "anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["result"],
        "title": "func_optionalOutput",
    }


def test_structured_output_dataclass():
    @dataclass
    class PersonDataClass:
        name: str
        age: int
        email: str | None = None
        tags: list[str] | None = None

    def func_returning_dataclass() -> PersonDataClass:  # pragma: no cover
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
    class PersonTypedDictOptional(TypedDict, total=False):
        name: str
        age: int

    def func_returning_typeddict_optional() -> PersonTypedDictOptional:  # pragma: no cover
        return {"name": "Dave"}

    meta = func_metadata(func_returning_typeddict_optional)
    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string", "default": None},
            "age": {"title": "Age", "type": "integer", "default": None},
        },
        "title": "PersonTypedDictOptional",
    }

    class PersonTypedDictRequired(TypedDict):
        name: str
        age: int
        email: str | None

    def func_returning_typeddict_required() -> PersonTypedDictRequired:  # pragma: no cover
        return {"name": "Eve", "age": 40, "email": None}

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
    class PersonClass:
        name: str
        age: int
        email: str | None

        def __init__(self, name: str, age: int, email: str | None = None):  # pragma: no cover
            self.name = name
            self.age = age
            self.email = email

    def func_returning_class() -> PersonClass:  # pragma: no cover
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
    class UnannotatedClass:
        def __init__(self, x, y):  # pragma: no cover
            self.x = x
            self.y = y

    def func_returning_unannotated() -> UnannotatedClass:  # pragma: no cover
        return UnannotatedClass(1, 2)

    meta = func_metadata(func_returning_unannotated)
    assert meta.output_schema is None


def test_tool_call_result_is_unstructured_and_not_converted():
    def func_returning_call_tool_result() -> CallToolResult:
        return CallToolResult(content=[])

    meta = func_metadata(func_returning_call_tool_result)

    assert meta.output_schema is None
    assert isinstance(meta.convert_result(func_returning_call_tool_result()), CallToolResult)


def test_tool_call_result_annotated_is_structured_and_converted():
    class PersonClass(BaseModel):
        name: str

    def func_returning_annotated_tool_call_result() -> Annotated[CallToolResult, PersonClass]:
        return CallToolResult(content=[], structured_content={"name": "Brandon"})

    meta = func_metadata(func_returning_annotated_tool_call_result)

    assert meta.output_schema == {
        "type": "object",
        "properties": {
            "name": {"title": "Name", "type": "string"},
        },
        "required": ["name"],
        "title": "PersonClass",
    }
    assert isinstance(meta.convert_result(func_returning_annotated_tool_call_result()), CallToolResult)


def test_tool_call_result_annotated_unioned_with_input_required_result_is_equivalent_to_the_bare_annotated_form():
    """Stripping `InputRequiredResult` must preserve the `Annotated[CallToolResult, Model]` special
    case: schema derives from `Model` and `convert_result` validates `structured_content` against it."""

    class PersonClass(BaseModel):
        name: str

    def fn_bare() -> Annotated[CallToolResult, PersonClass]:
        return CallToolResult(content=[], structured_content={"name": "Brandon"})

    def fn_iir() -> Annotated[CallToolResult, PersonClass] | InputRequiredResult:
        return CallToolResult(content=[], structured_content={"name": "Brandon"})

    bare = func_metadata(fn_bare)
    iir = func_metadata(fn_iir)
    assert iir.output_schema == bare.output_schema
    assert iir.wrap_output == bare.wrap_output
    assert isinstance(bare.convert_result(fn_bare()), CallToolResult)
    assert isinstance(iir.convert_result(fn_iir()), CallToolResult)


def test_tool_call_result_annotated_is_structured_and_invalid():
    class PersonClass(BaseModel):
        name: str

    def func_returning_annotated_tool_call_result() -> Annotated[CallToolResult, PersonClass]:
        return CallToolResult(content=[], structured_content={"person": "Brandon"})

    meta = func_metadata(func_returning_annotated_tool_call_result)

    with pytest.raises(ValueError):
        meta.convert_result(func_returning_annotated_tool_call_result())


def test_tool_call_result_in_optional_is_rejected():
    def func_optional_call_tool_result() -> CallToolResult | None:  # pragma: no cover
        return CallToolResult(content=[])

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_optional_call_tool_result)

    assert "Union or Optional" in str(exc_info.value)
    assert "CallToolResult" in str(exc_info.value)


def test_tool_call_result_in_union_is_rejected():
    def func_union_call_tool_result() -> str | CallToolResult:  # pragma: no cover
        return CallToolResult(content=[])

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_union_call_tool_result)

    assert "Union or Optional" in str(exc_info.value)
    assert "CallToolResult" in str(exc_info.value)


def test_tool_call_result_in_pipe_union_is_rejected():
    def func_pipe_union_call_tool_result() -> str | CallToolResult:  # pragma: no cover
        return CallToolResult(content=[])

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_pipe_union_call_tool_result)

    assert "Union or Optional" in str(exc_info.value)
    assert "CallToolResult" in str(exc_info.value)


def test_structured_output_with_field_descriptions():
    class ModelWithDescriptions(BaseModel):
        name: Annotated[str, Field(description="The person's full name")]
        age: Annotated[int, Field(description="Age in years", ge=0, le=150)]

    def func_with_descriptions() -> ModelWithDescriptions:  # pragma: no cover
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
    class Address(BaseModel):
        street: str
        city: str
        zipcode: str

    class PersonWithAddress(BaseModel):
        name: str
        address: Address

    def func_nested() -> PersonWithAddress:  # pragma: no cover
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
    class ConfigWithCallable:
        name: str
        # callable defaults are not JSON serializable and trigger pydantic warnings
        callback: Callable[[Any], Any] = lambda x: x * 2

    def func_returning_config_with_callable() -> ConfigWithCallable:  # pragma: no cover
        return ConfigWithCallable()

    meta = func_metadata(func_returning_config_with_callable)
    assert meta.output_schema is None

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_returning_config_with_callable, structured_output=True)
    assert "is not serializable for structured output" in str(exc_info.value)
    assert "ConfigWithCallable" in str(exc_info.value)

    class Point(NamedTuple):
        x: int
        y: int

    def func_returning_namedtuple() -> Point:  # pragma: no cover
        return Point(1, 2)

    meta = func_metadata(func_returning_namedtuple)
    assert meta.output_schema is None

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_returning_namedtuple, structured_output=True)
    assert "is not serializable for structured output" in str(exc_info.value)
    assert "Point" in str(exc_info.value)


def test_structured_output_aliases():
    """Test that field aliases are consistent between schema and output"""

    class ModelWithAliases(BaseModel):
        field_first: str | None = Field(default=None, alias="first", description="The first field.")
        field_second: str | None = Field(default=None, alias="second", description="The second field.")

    def func_with_aliases() -> ModelWithAliases:  # pragma: no cover
        return ModelWithAliases(**{"first": "hello", "second": "world"})

    meta = func_metadata(func_with_aliases)

    assert meta.output_schema is not None
    assert "first" in meta.output_schema["properties"]
    assert "second" in meta.output_schema["properties"]
    assert "field_first" not in meta.output_schema["properties"]
    assert "field_second" not in meta.output_schema["properties"]

    result = ModelWithAliases(**{"first": "hello", "second": "world"})
    converted = meta.convert_result(result)
    assert isinstance(converted, CallToolResult)
    structured_content = converted.structured_content
    assert structured_content is not None

    assert "first" in structured_content
    assert "second" in structured_content
    assert "field_first" not in structured_content
    assert "field_second" not in structured_content
    assert structured_content["first"] == "hello"
    assert structured_content["second"] == "world"

    result_with_defaults = ModelWithAliases()
    converted_defaults = meta.convert_result(result_with_defaults)
    assert isinstance(converted_defaults, CallToolResult)
    structured_content_defaults = converted_defaults.structured_content
    assert structured_content_defaults is not None

    assert "first" in structured_content_defaults
    assert "second" in structured_content_defaults
    assert "field_first" not in structured_content_defaults
    assert "field_second" not in structured_content_defaults
    assert structured_content_defaults["first"] is None
    assert structured_content_defaults["second"] is None


def test_basemodel_reserved_names():
    def func_with_reserved_names(  # pragma: no cover
        model_dump: str,
        model_validate: int,
        dict: list[str],
        json: dict[str, Any],
        validate: bool,
        copy: float,
        normal_param: str,
    ) -> str:
        return f"{model_dump}, {model_validate}, {dict}, {json}, {validate}, {copy}, {normal_param}"

    meta = func_metadata(func_with_reserved_names)

    schema = meta.arg_model.model_json_schema(by_alias=True)
    assert "model_dump" in schema["properties"]
    assert "model_validate" in schema["properties"]
    assert "dict" in schema["properties"]
    assert "json" in schema["properties"]
    assert "validate" in schema["properties"]
    assert "copy" in schema["properties"]
    assert "normal_param" in schema["properties"]


@pytest.mark.anyio
async def test_basemodel_reserved_names_validation():
    def func_with_reserved_names(
        model_dump: str,
        model_validate: int,
        dict: list[str],
        json: dict[str, Any],
        validate: bool,
        normal_param: str,
    ) -> str:
        return f"{model_dump}|{model_validate}|{len(dict)}|{json}|{validate}|{normal_param}"

    meta = func_metadata(func_with_reserved_names)

    result = await meta.call_fn_with_arg_validation(
        func_with_reserved_names,
        fn_is_async=False,
        arguments_to_validate={
            "model_dump": "test_dump",
            "model_validate": 42,
            "dict": ["a", "b", "c"],
            "json": {"key": "value"},
            "validate": True,
            "normal_param": "normal",
        },
        arguments_to_pass_directly=None,
    )

    assert result == "test_dump|42|3|{'key': 'value'}|True|normal"

    model_instance = meta.arg_model.model_validate(
        {
            "model_dump": "dump_value",
            "model_validate": 123,
            "dict": ["x", "y"],
            "json": {"foo": "bar"},
            "validate": False,
            "normal_param": "test",
        }
    )

    assert hasattr(model_instance, "model_dump")
    assert callable(model_instance.model_dump)

    # model_dump_one_level returns the original (non-aliased) parameter names
    dumped = model_instance.model_dump_one_level()
    assert dumped["model_dump"] == "dump_value"
    assert dumped["model_validate"] == 123
    assert dumped["dict"] == ["x", "y"]
    assert dumped["json"] == {"foo": "bar"}
    assert dumped["validate"] is False
    assert dumped["normal_param"] == "test"


def test_basemodel_reserved_names_with_json_preparsing():
    def func_with_reserved_json(  # pragma: no cover
        json: dict[str, Any],
        model_dump: list[int],
        normal: str,
    ) -> str:
        return "ok"

    meta = func_metadata(func_with_reserved_json)

    result = meta.pre_parse_json(
        {
            "json": '{"nested": "data"}',
            "model_dump": "[1, 2, 3]",
            "normal": "plain string",
        }
    )

    assert result["json"] == {"nested": "data"}
    assert result["model_dump"] == [1, 2, 3]
    assert result["normal"] == "plain string"


def test_disallowed_type_qualifier():
    def func_disallowed_qualifier() -> Final[int]:  # type: ignore
        pass  # pragma: no cover

    with pytest.raises(InvalidSignature) as exc_info:
        func_metadata(func_disallowed_qualifier)
    assert "return annotation contains an invalid type qualifier" in str(exc_info.value)


def test_preserves_pydantic_metadata():
    def func_with_metadata() -> Annotated[int, Field(gt=1)]: ...  # pragma: no branch

    meta = func_metadata(func_with_metadata)

    assert meta.output_schema is not None
    assert meta.output_schema["properties"]["result"] == {"exclusiveMinimum": 1, "title": "Result", "type": "integer"}


def test_convert_result_passes_input_required_result_through_unchanged():
    def fn() -> str | InputRequiredResult: ...  # pragma: no branch

    meta = func_metadata(fn)
    irr = InputRequiredResult(request_state="opaque")
    assert meta.convert_result(irr) is irr


def test_input_required_result_return_annotation_yields_no_output_schema():
    def fn() -> InputRequiredResult: ...  # pragma: no branch

    meta = func_metadata(fn)
    assert meta.output_schema is None
    assert meta.output_model is None


def test_union_with_input_required_result_derives_schema_from_residual_arm():
    def fn() -> str | InputRequiredResult: ...  # pragma: no branch

    meta = func_metadata(fn)
    assert meta.output_schema is not None
    assert meta.output_schema["properties"]["result"]["type"] == "string"
    converted = meta.convert_result("hello")
    assert isinstance(converted, CallToolResult)
    assert converted.structured_content == {"result": "hello"}
    irr = InputRequiredResult(request_state="opaque")
    assert meta.convert_result(irr) is irr


def test_call_tool_result_unioned_with_input_required_result_is_accepted():
    def fn() -> CallToolResult | InputRequiredResult: ...  # pragma: no branch

    meta = func_metadata(fn)
    assert meta.output_schema is None


def test_basemodel_union_input_required_result_derives_model_schema():
    class Payload(BaseModel):
        x: int

    def fn() -> Payload | InputRequiredResult: ...  # pragma: no branch

    meta = func_metadata(fn)
    assert meta.output_model is Payload
    assert meta.wrap_output is False
    assert meta.output_schema == Payload.model_json_schema()


def test_call_tool_result_in_union_with_input_required_result_is_still_rejected():
    def fn() -> CallToolResult | str | InputRequiredResult: ...  # pragma: no branch

    with pytest.raises(InvalidSignature, match="CallToolResult cannot be used in Union"):
        func_metadata(fn)


def test_union_of_only_input_required_subclasses_yields_no_output_schema():
    class StepA(InputRequiredResult):
        pass

    class StepB(InputRequiredResult):
        pass

    def fn() -> StepA | StepB: ...  # pragma: no branch

    meta = func_metadata(fn)
    assert meta.output_schema is None
