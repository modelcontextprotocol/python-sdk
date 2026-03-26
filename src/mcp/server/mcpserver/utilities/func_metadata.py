import functools
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from itertools import chain
from types import GenericAlias
from typing import Annotated, Any, cast, get_args, get_origin, get_type_hints

import anyio
import anyio.to_thread
import pydantic_core
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, create_model
from pydantic.fields import FieldInfo
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaWarningKind
from typing_extensions import is_typeddict
from typing_inspection.introspection import (
    UNKNOWN,
    AnnotationSource,
    ForbiddenQualifier,
    inspect_annotation,
    is_union_origin,
)

from mcp.server.mcpserver.exceptions import InvalidSignature
from mcp.server.mcpserver.utilities.logging import get_logger
from mcp.server.mcpserver.utilities.types import Audio, Image
from mcp.types import CallToolResult, ContentBlock, TextContent

logger = get_logger(__name__)


class StrictJsonSchema(GenerateJsonSchema):
    """A JSON schema generator that raises exceptions instead of emitting warnings.

    This is used to detect non-serializable types during schema generation.
    """

    def emit_warning(self, kind: JsonSchemaWarningKind, detail: str) -> None:
        # Raise an exception instead of emitting a warning
        raise ValueError(f"JSON schema warning: {kind} - {detail}")


class ArgModelBase(BaseModel):
    """A model representing the arguments to a function."""

    def model_dump_one_level(self) -> dict[str, Any]:
        """Return a dict of the model's fields, one level deep.

        That is, sub-models etc are not dumped - they are kept as Pydantic models.
        """
        kwargs: dict[str, Any] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            # Use the alias if it exists, otherwise use the field name
            output_name = field_info.alias if field_info.alias else field_name
            kwargs[output_name] = value
        return kwargs

    model_config = ConfigDict(arbitrary_types_allowed=True)


class FuncMetadata(BaseModel):
    arg_model: Annotated[type[ArgModelBase], WithJsonSchema(None)]
    output_schema: dict[str, Any] | None = None
    output_model: Annotated[type[BaseModel], WithJsonSchema(None)] | None = None
    wrap_output: bool = False

    async def call_fn_with_arg_validation(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        fn_is_async: bool,
        arguments_to_validate: dict[str, Any],
        arguments_to_pass_directly: dict[str, Any] | None,
    ) -> Any:
        """Call the given function with arguments validated and injected.

        Arguments are first attempted to be parsed from JSON, then validated against
        the argument model, before being passed to the function.
        """
        arguments_pre_parsed = self.pre_parse_json(arguments_to_validate)
        arguments_parsed_model = self.arg_model.model_validate(arguments_pre_parsed)
        arguments_parsed_dict = arguments_parsed_model.model_dump_one_level()

        arguments_parsed_dict |= arguments_to_pass_directly or {}

        if fn_is_async:
            return await fn(**arguments_parsed_dict)
        else:
            return await anyio.to_thread.run_sync(functools.partial(fn, **arguments_parsed_dict))

    def convert_result(self, result: Any) -> Any:
        """Convert a function call result to the format for the lowlevel tool call handler.

        - If output_model is None, return the unstructured content directly.
        - If output_model is not None, convert the result to structured output format
            (dict[str, Any]) and return both unstructured and structured content.

        Note: we return unstructured content here **even though the lowlevel server
        tool call handler provides generic backwards compatibility serialization of
        structured content**. This is for MCPServer backwards compatibility: we need to
        retain MCPServer's ad hoc conversion logic for constructing unstructured output
        from function return values, whereas the lowlevel server simply serializes
        the structured output.
        """
        if isinstance(result, CallToolResult):
            if self.output_schema is not None:
                assert self.output_model is not None, "Output model must be set if output schema is defined"
                self.output_model.model_validate(result.structured_content)
            return result

        unstructured_content = _convert_to_content(result)

        if self.output_schema is None:
            return unstructured_content
        else:
            if self.wrap_output:
                result = {"result": result}

            assert self.output_model is not None, "Output model must be set if output schema is defined"
            validated = self.output_model.model_validate(result)
            structured_content = validated.model_dump(mode="json", by_alias=True)

            return (unstructured_content, structured_content)

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Pre-parse data from JSON.

        Return a dict with the same keys as input but with values parsed from JSON
        if appropriate.

        This is to handle cases like `["a", "b", "c"]` being passed in as JSON inside
        a string rather than an actual list. Claude Desktop is prone to this - in fact
        it seems incapable of NOT doing this. For sub-models, it tends to pass
        dicts (JSON objects) as JSON strings, which can be pre-parsed here.
        """
        new_data = data.copy()  # Shallow copy

        # Build a mapping from input keys (including aliases) to field info
        key_to_field_info: dict[str, FieldInfo] = {}
        for field_name, field_info in self.arg_model.model_fields.items():
            # Map both the field name and its alias (if any) to the field info
            key_to_field_info[field_name] = field_info
            if field_info.alias:
                key_to_field_info[field_info.alias] = field_info

        for data_key, data_value in data.items():
            if data_key not in key_to_field_info:  # pragma: no cover
                continue

            field_info = key_to_field_info[data_key]
            if isinstance(data_value, str) and field_info.annotation is not str:
                try:
                    pre_parsed = json.loads(data_value)
                except json.JSONDecodeError:
                    continue  # Not JSON - skip
                if isinstance(pre_parsed, str | int | float):
                    # This is likely that the raw value is e.g. `"hello"` which we
                    # Should really be parsed as '"'hello'"' in Python - but if we parse
                    # it as JSON it'll turn into just 'hello'. So we skip it.
                    continue
                new_data[data_key] = pre_parsed
        assert new_data.keys() == data.keys()
        return new_data

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )


def func_metadata(
    func: Callable[..., Any],
    skip_names: Sequence[str] = (),
    structured_output: bool | None = None,
) -> FuncMetadata:
    """Given a function, return metadata including a Pydantic model representing its signature.

    The use case for this is
    ```
    meta = func_metadata(func)
    validated_args = meta.arg_model.model_validate(some_raw_data_dict)
    return func(**validated_args.model_dump_one_level())
    ```

    **critically** it also provides a pre-parse helper to attempt to parse things from
    JSON.

    Args:
        func: The function to convert to a Pydantic model
        skip_names: A list of parameter names to skip. These will not be included in
            the model.
        structured_output: Controls whether the tool's output is structured or unstructured
            - If None, auto-detects based on the function's return type annotation
            - If True, creates a structured tool (return type annotation permitting)
            - If False, unconditionally creates an unstructured tool

            If structured, creates a Pydantic model for the function's result based on its annotation.
            Supports various return types:
            - BaseModel subclasses (used directly)
            - Primitive types (str, int, float, bool, bytes, None) - wrapped in a
                model with a 'result' field
            - TypedDict - converted to a Pydantic model with same fields
            - Dataclasses and other annotated classes - converted to Pydantic models
            - Generic types (list, dict, Union, etc.) - wrapped in a model with a 'result' field

    Returns:
        A FuncMetadata object containing:
        - arg_model: A Pydantic model representing the function's arguments
        - output_model: A Pydantic model for the return type if the output is structured
        - wrap_output: Whether the function result needs to be wrapped in {"result": ...}
            for structured output.
    """
    sig = _get_function_signature(func)
    arguments_model = _build_arg_model(sig, func.__name__, skip_names)

    if structured_output is False:
        return FuncMetadata(arg_model=arguments_model)

    resolved = _resolve_return_annotation(sig, structured_output, func.__name__)
    if resolved is None:
        return FuncMetadata(arg_model=arguments_model)

    original_annotation, return_type_expr = resolved

    output_model, output_schema, wrap_output = _try_create_model_and_schema(
        original_annotation, return_type_expr, func.__name__
    )

    if output_model is None and structured_output is True:
        raise InvalidSignature(
            f"Function {func.__name__}: return type {return_type_expr} is not serializable for structured output"
        )

    return FuncMetadata(
        arg_model=arguments_model,
        output_schema=output_schema,
        output_model=output_model,
        wrap_output=wrap_output,
    )


def _get_function_signature(func: Callable[..., Any]) -> inspect.Signature:
    """Get the signature of a function, raising InvalidSignature on failure."""
    try:
        return inspect.signature(func, eval_str=True)
    except NameError as e:  # pragma: no cover
        raise InvalidSignature(f"Unable to evaluate type annotations for callable {func.__name__!r}") from e


def _build_arg_model(
    sig: inspect.Signature,
    func_name: str,
    skip_names: Sequence[str] = (),
) -> type[ArgModelBase]:
    """Build a Pydantic model representing the function's arguments.

    Iterates over the function's parameters, handling type annotations, defaults,
    and BaseModel attribute name conflicts (via aliasing).

    Args:
        sig: The function's inspect.Signature.
        func_name: The function's name (used for the model name).
        skip_names: Parameter names to exclude from the model.

    Returns:
        A dynamically created Pydantic model class.
    """
    params = sig.parameters
    dynamic_pydantic_model_params: dict[str, Any] = {}
    for param in params.values():
        if param.name.startswith("_"):  # pragma: no cover
            raise InvalidSignature(f"Parameter {param.name} of {func_name} cannot start with '_'")
        if param.name in skip_names:
            continue

        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
        field_name = param.name
        field_kwargs: dict[str, Any] = {}
        field_metadata: list[Any] = []

        if param.annotation is inspect.Parameter.empty:
            field_metadata.append(WithJsonSchema({"title": param.name, "type": "string"}))
        # Check if the parameter name conflicts with BaseModel attributes
        # This is necessary because Pydantic warns about shadowing parent attributes
        if hasattr(BaseModel, field_name) and callable(getattr(BaseModel, field_name)):
            # Use an alias to avoid the shadowing warning
            field_kwargs["alias"] = field_name
            # Use a prefixed field name
            field_name = f"field_{field_name}"

        if param.default is not inspect.Parameter.empty:
            dynamic_pydantic_model_params[field_name] = (
                Annotated[(annotation, *field_metadata, Field(**field_kwargs))],
                param.default,
            )
        else:
            dynamic_pydantic_model_params[field_name] = Annotated[(annotation, *field_metadata, Field(**field_kwargs))]

    return create_model(
        f"{func_name}Arguments",
        __base__=ArgModelBase,
        **dynamic_pydantic_model_params,
    )


def _resolve_return_annotation(
    sig: inspect.Signature,
    structured_output: bool | None,
    func_name: str,
) -> tuple[Any, Any] | None:
    """Resolve and validate the function's return type annotation for structured output.

    Handles special cases including CallToolResult, Annotated metadata, and Union types.

    Args:
        sig: The function's inspect.Signature.
        structured_output: Whether structured output is requested (None for auto-detect).
        func_name: The function's name (used for error messages).

    Returns:
        A tuple of (original_annotation, type_expr) if structured output should be
        attempted, or None if no structured output is needed.
    """
    if sig.return_annotation is inspect.Parameter.empty and structured_output is True:
        raise InvalidSignature(f"Function {func_name}: return annotation required for structured output")

    try:
        inspected_return_ann = inspect_annotation(sig.return_annotation, annotation_source=AnnotationSource.FUNCTION)
    except ForbiddenQualifier as e:
        raise InvalidSignature(f"Function {func_name}: return annotation contains an invalid type qualifier") from e

    return_type_expr = inspected_return_ann.type

    # `AnnotationSource.FUNCTION` allows no type qualifier to be used, so `return_type_expr` is guaranteed to *not* be
    # unknown (i.e. a bare `Final`).
    assert return_type_expr is not UNKNOWN

    if is_union_origin(get_origin(return_type_expr)):
        args = get_args(return_type_expr)
        # Check if CallToolResult appears in the union (excluding None for Optional check)
        if any(isinstance(arg, type) and issubclass(arg, CallToolResult) for arg in args if arg is not type(None)):
            raise InvalidSignature(
                f"Function {func_name}: CallToolResult cannot be used in Union or Optional types. "
                "To return empty results, use: CallToolResult(content=[])"
            )

    original_annotation: Any
    # if the typehint is CallToolResult, the user either intends to return without validation
    # or they provided validation as Annotated metadata
    if isinstance(return_type_expr, type) and issubclass(return_type_expr, CallToolResult):
        if inspected_return_ann.metadata:
            return_type_expr = inspected_return_ann.metadata[0]
            if len(inspected_return_ann.metadata) >= 2:
                # Reconstruct the original annotation, by preserving the remaining metadata,
                # i.e. from `Annotated[CallToolResult, ReturnType, Gt(1)]` to
                # `Annotated[ReturnType, Gt(1)]`:
                original_annotation = Annotated[
                    (return_type_expr, *inspected_return_ann.metadata[1:])
                ]  # pragma: no cover
            else:
                # We only had `Annotated[CallToolResult, ReturnType]`, treat the original annotation
                # as being `ReturnType`:
                original_annotation = return_type_expr
        else:
            return None
    else:
        original_annotation = sig.return_annotation

    return original_annotation, cast(Any, return_type_expr)


def _try_create_model_and_schema(
    original_annotation: Any,
    type_expr: Any,
    func_name: str,
) -> tuple[type[BaseModel] | None, dict[str, Any] | None, bool]:
    """Try to create a model and schema for the given annotation without warnings.

    Args:
        original_annotation: The original return annotation (may be wrapped in `Annotated`).
        type_expr: The underlying type expression derived from the return annotation
            (`Annotated` and type qualifiers were stripped).
        func_name: The name of the function.

    Returns:
        tuple of (model or None, schema or None, wrap_output)
        Model and schema are None if warnings occur or creation fails.
        wrap_output is True if the result needs to be wrapped in {"result": ...}
    """
    model, wrap_output = _create_output_model(original_annotation, type_expr, func_name)

    if model is not None:
        schema = _try_generate_strict_schema(model, type_expr, func_name)
        if schema is None:
            return None, None, False
        return model, schema, wrap_output

    return None, None, False


def _create_output_model(
    original_annotation: Any,
    type_expr: Any,
    func_name: str,
) -> tuple[type[BaseModel] | None, bool]:
    """Create a Pydantic model for the function's return type.

    Dispatches to the appropriate model creation strategy based on the type:
    - None -> wrapped model
    - GenericAlias (list, dict, Union, etc.) -> wrapped or dict model
    - BaseModel subclasses -> used directly
    - TypedDict -> converted to Pydantic model
    - Primitive types -> wrapped model
    - Classes with type hints -> converted to Pydantic model

    Args:
        original_annotation: The original return annotation.
        type_expr: The underlying type expression.
        func_name: The function's name.

    Returns:
        A tuple of (model or None, wrap_output).
    """
    # Special case: None
    if type_expr is None:
        return _create_wrapped_model(func_name, original_annotation), True

    # Handle GenericAlias types (list[str], dict[str, int], Union[str, int], etc.)
    if isinstance(type_expr, GenericAlias):
        origin = get_origin(type_expr)

        # Special case: dict with string keys can use RootModel
        if origin is dict:
            args = get_args(type_expr)
            if len(args) == 2 and args[0] is str:
                # TODO: should we use the original annotation? We are losing any potential `Annotated`
                # metadata for Pydantic here:
                return _create_dict_model(func_name, type_expr), False
            else:
                # dict with non-str keys needs wrapping
                return _create_wrapped_model(func_name, original_annotation), True
        else:
            # All other generic types need wrapping (list, tuple, Union, Optional, etc.)
            return _create_wrapped_model(func_name, original_annotation), True

    # Handle regular type objects
    if isinstance(type_expr, type):
        type_annotation = cast(type[Any], type_expr)

        # Case 1: BaseModel subclasses (can be used directly)
        if issubclass(type_annotation, BaseModel):
            return type_annotation, False

        # Case 2: TypedDicts:
        if is_typeddict(type_annotation):
            return _create_model_from_typeddict(type_annotation), False

        # Case 3: Primitive types that need wrapping
        if type_annotation in (str, int, float, bool, bytes, type(None)):
            return _create_wrapped_model(func_name, original_annotation), True

        # Case 4: Other class types (dataclasses, regular classes with annotations)
        type_hints = get_type_hints(type_annotation)
        if type_hints:
            # Classes with type hints can be converted to Pydantic models
            return _create_model_from_class(type_annotation, type_hints), False
        # Classes without type hints are not serializable
        return None, False

    # Handle any other types not covered above
    # This includes typing constructs that aren't GenericAlias in Python 3.10
    # (e.g., Union, Optional in some Python versions)
    return _create_wrapped_model(func_name, original_annotation), True


def _try_generate_strict_schema(
    model: type[BaseModel],
    type_expr: Any,
    func_name: str,
) -> dict[str, Any] | None:
    """Try to generate a JSON schema using StrictJsonSchema.

    Returns the schema dict on success, or None if the type cannot be serialized.
    """
    try:
        return model.model_json_schema(schema_generator=StrictJsonSchema)
    except (TypeError, ValueError, pydantic_core.SchemaError, pydantic_core.ValidationError) as e:
        # These are expected errors when a type can't be converted to a Pydantic schema
        # TypeError: When Pydantic can't handle the type
        # ValueError: When there are issues with the type definition (including our custom warnings)
        # SchemaError: When Pydantic can't build a schema
        # ValidationError: When validation fails
        logger.info(f"Cannot create schema for type {type_expr} in {func_name}: {type(e).__name__}: {e}")
        return None


_no_default = object()


def _create_model_from_class(cls: type[Any], type_hints: dict[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model from an ordinary class.

    The created model will:
    - Have the same name as the class
    - Have fields with the same names and types as the class's fields
    - Include all fields whose type does not include None in the set of required fields

    Precondition: cls must have type hints (i.e., `type_hints` is non-empty)
    """
    model_fields: dict[str, Any] = {}
    for field_name, field_type in type_hints.items():
        if field_name.startswith("_"):  # pragma: no cover
            continue

        default = getattr(cls, field_name, _no_default)
        if default is _no_default:
            model_fields[field_name] = field_type
        else:
            model_fields[field_name] = (field_type, default)

    return create_model(cls.__name__, __config__=ConfigDict(from_attributes=True), **model_fields)


def _create_model_from_typeddict(td_type: type[Any]) -> type[BaseModel]:
    """Create a Pydantic model from a TypedDict.

    The created model will have the same name and fields as the TypedDict.
    """
    type_hints = get_type_hints(td_type)
    required_keys = getattr(td_type, "__required_keys__", set(type_hints.keys()))

    model_fields: dict[str, Any] = {}
    for field_name, field_type in type_hints.items():
        if field_name not in required_keys:
            # For optional TypedDict fields, set default=None
            # This makes them not required in the Pydantic model
            # The model should use exclude_unset=True when dumping to get TypedDict semantics
            model_fields[field_name] = (field_type, None)
        else:
            model_fields[field_name] = field_type

    return create_model(td_type.__name__, **model_fields)


def _create_wrapped_model(func_name: str, annotation: Any) -> type[BaseModel]:
    """Create a model that wraps a type in a 'result' field.

    This is used for primitive types, generic types like list/dict, etc.
    """
    model_name = f"{func_name}Output"

    return create_model(model_name, result=annotation)


def _create_dict_model(func_name: str, dict_annotation: Any) -> type[BaseModel]:
    """Create a RootModel for dict[str, T] types."""
    # TODO(Marcelo): We should not rely on RootModel for this.
    from pydantic import RootModel  # noqa: TID251

    class DictModel(RootModel[dict_annotation]):
        pass

    # Give it a meaningful name
    DictModel.__name__ = f"{func_name}DictOutput"
    DictModel.__qualname__ = f"{func_name}DictOutput"

    return DictModel


def _convert_to_content(result: Any) -> Sequence[ContentBlock]:
    """Convert a result to a sequence of content objects.

    Note: This conversion logic comes from previous versions of MCPServer and is being
    retained for purposes of backwards compatibility. It produces different unstructured
    output than the lowlevel server tool call handler, which just serializes structured
    content verbatim.
    """
    if result is None:  # pragma: no cover
        return []

    if isinstance(result, ContentBlock):
        return [result]

    if isinstance(result, Image):
        return [result.to_image_content()]

    if isinstance(result, Audio):
        return [result.to_audio_content()]

    if isinstance(result, list | tuple):
        return list(
            chain.from_iterable(
                _convert_to_content(item)
                for item in result  # type: ignore
            )
        )

    if not isinstance(result, str):
        result = pydantic_core.to_json(result, fallback=str, indent=2).decode()

    return [TextContent(type="text", text=result)]
