"""Tests for Optional parameter handling in func_metadata.

This module tests the fix for issue #1402 where Optional[T] parameters
without explicit defaults were incorrectly marked as required in JSON schemas.
"""


from pydantic import Field

from mcp.server.fastmcp.utilities.func_metadata import func_metadata


def test_optional_parameters_not_required():
    """Test that Optional parameters without defaults are not marked as required."""

    def func_with_optional_params(
        required: str = Field(description="This should be required"),
        optional: str | None = Field(description="This should be optional"),
        optional_with_default: str | None = Field(default="hello", description="This should be optional with default"),
        optional_with_union_type: str | None = Field(description="This should be optional"),
        optional_with_union_type_and_default: str | None | None = Field(
            default="hello", description="This should be optional with default"
        ),
    ) -> str:
        return (
            f"{required}|{optional}|{optional_with_default}|"
            f"{optional_with_union_type}|{optional_with_union_type_and_default}"
        )

    meta = func_metadata(func_with_optional_params)
    schema = meta.arg_model.model_json_schema()

    # Only 'required' parameter should be in the required list
    assert schema["required"] == ["required"]

    # All optional parameters should have default=None
    assert schema["properties"]["optional"]["default"] is None
    assert schema["properties"]["optional_with_default"]["default"] == "hello"
    assert schema["properties"]["optional_with_union_type"]["default"] is None
    assert schema["properties"]["optional_with_union_type_and_default"]["default"] == "hello"


def test_required_parameters_still_required():
    """Test that non-optional parameters remain required."""

    def func_with_required_params(
        required_str: str = Field(description="Required string"),
        required_int: int = Field(description="Required int"),
        optional: str | None = Field(description="Optional string"),
    ) -> str:
        return f"{required_str}|{required_int}|{optional}"

    meta = func_metadata(func_with_required_params)
    schema = meta.arg_model.model_json_schema()

    # Both required parameters should be in the required list
    assert set(schema["required"]) == {"required_str", "required_int"}

    # Optional parameter should have default=None
    assert schema["properties"]["optional"]["default"] is None


def test_optional_with_explicit_none_default():
    """Test Optional parameters with explicit None default."""

    def func_with_explicit_none(
        optional_explicit: str | None = Field(default=None, description="Explicit None default"),
        optional_implicit: str | None = Field(description="Implicit None default"),
    ) -> str:
        return f"{optional_explicit}|{optional_implicit}"

    meta = func_metadata(func_with_explicit_none)
    schema = meta.arg_model.model_json_schema()

    # No parameters should be required
    assert schema.get("required", []) == []

    # Both should have None defaults
    assert schema["properties"]["optional_explicit"]["default"] is None
    assert schema["properties"]["optional_implicit"]["default"] is None


def test_mixed_optional_types():
    """Test various Optional type patterns."""

    def func_with_mixed_optionals(
        union_pipe: str | None = Field(description="str | None"),
        union_optional: str | None = Field(description="Optional[str]"),
        union_multi: str | int | None = Field(description="str | int | None"),
        required: str = Field(description="Required"),
    ) -> str:
        return f"{union_pipe}|{union_optional}|{union_multi}|{required}"

    meta = func_metadata(func_with_mixed_optionals)
    schema = meta.arg_model.model_json_schema()

    # Only 'required' should be in required list
    assert schema["required"] == ["required"]

    # All optional types should have None defaults
    assert schema["properties"]["union_pipe"]["default"] is None
    assert schema["properties"]["union_optional"]["default"] is None
    assert schema["properties"]["union_multi"]["default"] is None


def test_runtime_behavior_with_optional_params():
    """Test that the actual function calls work correctly with optional parameters."""

    def func_with_optionals(
        required: str = Field(description="Required"),
        optional: str | None = Field(description="Optional"),
    ) -> str:
        return f"required={required}, optional={optional}"

    meta = func_metadata(func_with_optionals)

    # Test with both parameters
    result1 = meta.arg_model(required="test", optional="value")
    assert result1.required == "test"
    assert result1.optional == "value"

    # Test with only required parameter
    result2 = meta.arg_model(required="test")
    assert result2.required == "test"
    assert result2.optional is None

    # Test with explicit None for optional
    result3 = meta.arg_model(required="test", optional=None)
    assert result3.required == "test"
    assert result3.optional is None
