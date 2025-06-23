import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, is_dataclass
from typing import (
    Annotated,
    Any,
    ForwardRef,
    Literal,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    WithJsonSchema,
    create_model,
)
from pydantic._internal._typing_extra import eval_type_backport
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from mcp.server.fastmcp.exceptions import InvalidSignature, ToolError
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

OutputConversion = Literal["none", "wrapped", "namedtuple", "class"]


class ArgModelBase(BaseModel):
    """A model representing the arguments to a function."""

    def model_dump_one_level(self) -> dict[str, Any]:
        """Return a dict of the model's fields, one level deep.

        That is, sub-models etc are not dumped - they are kept as pydantic models.
        """
        kwargs: dict[str, Any] = {}
        for field_name in self.__class__.model_fields.keys():
            kwargs[field_name] = getattr(self, field_name)
        return kwargs

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )


class FuncMetadata(BaseModel):
    arg_model: Annotated[type[ArgModelBase], WithJsonSchema(None)]
    output_model: Annotated[type[BaseModel], WithJsonSchema(None)] | None = None
    output_conversion: OutputConversion = "none"
    # We can add things in the future like
    #  - Maybe some args are excluded from attempting to parse from JSON
    #  - Maybe some args are special (like context) for dependency injection

    async def call_fn_with_arg_validation(
        self,
        fn: Callable[..., Any] | Awaitable[Any],
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
            if isinstance(fn, Awaitable):
                return await fn
            return await fn(**arguments_parsed_dict)
        if isinstance(fn, Callable):
            return fn(**arguments_parsed_dict)
        raise TypeError("fn must be either Callable or Awaitable")

    def to_validated_dict(self, result: Any) -> dict[str, Any]:
        """Validate and convert the result to a dict after validation."""
        if self.output_model is None:
            raise ValueError("No output model to validate against")

        match self.output_conversion:
            case "wrapped":
                converted = _convert_wrapped_result(result)
            case "namedtuple":
                converted = _convert_namedtuple_result(result)
            case "class":
                converted = _convert_class_result(result)
            case "none":
                converted = result

        try:
            validated = self.output_model.model_validate(converted)
        except Exception as e:
            raise ToolError(f"Output validation failed: {e}") from e

        return validated.model_dump()

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Pre-parse data from JSON.

        Return a dict with same keys as input but with values parsed from JSON
        if appropriate.

        This is to handle cases like `["a", "b", "c"]` being passed in as JSON inside
        a string rather than an actual list. Claude desktop is prone to this - in fact
        it seems incapable of NOT doing this. For sub-models, it tends to pass
        dicts (JSON objects) as JSON strings, which can be pre-parsed here.
        """
        new_data = data.copy()  # Shallow copy
        for field_name in self.arg_model.model_fields.keys():
            if field_name not in data.keys():
                continue
            if isinstance(data[field_name], str):
                try:
                    pre_parsed = json.loads(data[field_name])
                except json.JSONDecodeError:
                    continue  # Not JSON - skip
                if isinstance(pre_parsed, str | int | float):
                    # This is likely that the raw value is e.g. `"hello"` which we
                    # Should really be parsed as '"hello"' in Python - but if we parse
                    # it as JSON it'll turn into just 'hello'. So we skip it.
                    continue
                new_data[field_name] = pre_parsed
        assert new_data.keys() == data.keys()
        return new_data

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )


def func_metadata(
    func: Callable[..., Any],
    skip_names: Sequence[str] = (),
    structured_output: bool = False,
) -> FuncMetadata:
    """Given a function, return metadata including a pydantic model representing its
    signature.

    The use case for this is
    ```
    meta = func_metadata(func)
    validated_args = meta.arg_model.model_validate(some_raw_data_dict)
    return func(**validated_args.model_dump_one_level())
    ```

    **critically** it also provides pre-parse helper to attempt to parse things from
    JSON.

    Args:
        func: The function to convert to a pydantic model
        skip_names: A list of parameter names to skip. These will not be included in
            the model.
        structured_output: If True, creates a Pydantic model for the function's return
            type. The function must have a return type annotation when this is True.
            Supports various return types:
            - BaseModel subclasses (used directly)
            - Primitive types (str, int, float, bool, bytes, None) - wrapped in a
              model with a 'result' field
            - TypedDict - converted to a Pydantic model with same fields
            - NamedTuple - converted to a Pydantic model with same fields
            - Dataclasses and other annotated classes - converted to Pydantic models
            - Generic types (list, dict, Union, etc.) - wrapped in a model with a 'result' field
            Raises InvalidSignature if the return type has no annotations.
    Returns:
        A FuncMetadata object containing:
        - arg_model: A pydantic model representing the function's arguments
        - output_model: A pydantic model for the return type (if structured_output=True)
    """
    sig = _get_typed_signature(func)
    params = sig.parameters
    dynamic_pydantic_model_params: dict[str, Any] = {}
    globalns = getattr(func, "__globals__", {})
    for param in params.values():
        if param.name.startswith("_"):
            raise InvalidSignature(f"Parameter {param.name} of {func.__name__} cannot start with '_'")
        if param.name in skip_names:
            continue
        annotation = param.annotation

        # `x: None` / `x: None = None`
        if annotation is None:
            annotation = Annotated[
                None,
                Field(default=param.default if param.default is not inspect.Parameter.empty else PydanticUndefined),
            ]

        # Untyped field
        if annotation is inspect.Parameter.empty:
            annotation = Annotated[
                Any,
                Field(),
                # 🤷
                WithJsonSchema({"title": param.name, "type": "string"}),
            ]

        field_info = FieldInfo.from_annotated_attribute(
            _get_typed_annotation(annotation, globalns),
            param.default if param.default is not inspect.Parameter.empty else PydanticUndefined,
        )
        dynamic_pydantic_model_params[param.name] = (field_info.annotation, field_info)
        continue

    arguments_model = create_model(
        f"{func.__name__}Arguments",
        **dynamic_pydantic_model_params,
        __base__=ArgModelBase,
    )

    output_model = None
    output_conversion = "none"
    if structured_output:
        if sig.return_annotation is inspect.Parameter.empty:
            raise InvalidSignature(f"Function {func.__name__}: return annotation required for structured output")

        output_info = FieldInfo.from_annotation(_get_typed_annotation(sig.return_annotation, globalns))
        annotation = output_info.annotation

        if _needs_wrapper(annotation):
            output_model = _create_wrapped_model(func.__name__, annotation, output_info)
            output_conversion = "wrapped"
        elif _is_dict_str_any(annotation):
            output_model = _create_dict_model(func.__name__, annotation)
            output_conversion = "none"
        elif isinstance(annotation, type):
            if issubclass(annotation, BaseModel):
                output_model = annotation
                output_conversion = "none"
            elif _is_typeddict(annotation):
                output_model = _create_model_from_typeddict(annotation, globalns)
                output_conversion = "none"
            elif _is_namedtuple(annotation):
                output_model = _create_model_from_namedtuple(annotation, globalns)
                output_conversion = "namedtuple"
            else:
                output_model = _create_model_from_class(annotation, globalns)
                output_conversion = "class"
        else:
            raise InvalidSignature(
                f"Function {func.__name__}: return type {annotation} is not supported for structured output. "
            )

    return FuncMetadata(arg_model=arguments_model, output_model=output_model, output_conversion=output_conversion)


def _is_typeddict(annotation: type[Any]) -> bool:
    return hasattr(annotation, "__annotations__") and issubclass(annotation, dict)


def _is_namedtuple(annotation: type[Any]) -> bool:
    return hasattr(annotation, "_fields") and issubclass(annotation, tuple)


def _is_primitive_type(annotation: Any) -> bool:
    return annotation in (str, int, float, bool, bytes, type(None)) or annotation is None


def _is_dict_str_any(annotation: Any) -> bool:
    """Check if annotation is dict[str, T] for any T."""
    if get_origin(annotation) is dict:
        args = get_args(annotation)
        return len(args) == 2 and args[0] is str
    return False


def _needs_wrapper(annotation: Any) -> bool:
    """Check if a return type annotation needs to be wrapped in a result model.

    Returns True for:
    - Primitive types (str, int, float, bool, bytes, None)
    - Generic types (list[T], dict[K,V], etc.) EXCEPT dict[str, T]
    - Non-type instances (Union, Optional, Literal, Any, etc.)

    Returns False for:
    - BaseModel subclasses
    - TypedDict types
    - NamedTuple types
    - Ordinary classes with annotations
    - dict[str, T] for any T (can be used directly as a model)
    """
    if _is_dict_str_any(annotation):
        # dict[str, T] doesn't need wrapping
        return False

    if not isinstance(annotation, type):
        # Non-type instances (Union, Optional, Literal, Any, etc.)
        return True

    if get_origin(annotation) is not None:
        # Generic types (list[T], dict[K,V], etc.)
        return True

    if _is_primitive_type(annotation):
        # Primitive types (str, int, float, bool, bytes, None)
        return True

    # Everything else (classes, BaseModel, TypedDict, etc.) doesn't need wrapping
    return False


def _create_model_from_class(cls: type[Any], globalns: dict[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model from an ordinary class.

    The created model will:
    - Have the same name as the class
    - Have fields with the same names and types as the class's fields
    - Include all fields whose type does not include None in the set of required fields
    """
    type_hints = get_type_hints(cls)

    if not type_hints:
        raise InvalidSignature(
            f"Cannot infer a schema for return type {cls.__name__}. "
            f"The class has no type annotations. Consider using a Pydantic BaseModel, "
            f"dataclass, or TypedDict instead."
        )

    model_fields: dict[str, Any] = {}
    for field_name, field_type in type_hints.items():
        if field_name.startswith("_"):
            continue

        default = getattr(cls, field_name, PydanticUndefined)
        field_info = FieldInfo.from_annotated_attribute(field_type, default)
        model_fields[field_name] = (field_info.annotation, field_info)

    return create_model(cls.__name__, **model_fields, __base__=BaseModel)


def _convert_class_result(result: Any) -> dict[str, Any]:
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)

    return dict(vars(result))


def _create_model_from_typeddict(td_type: type[Any], globalns: dict[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model from a TypedDict.

    The created model will have the same name and fields as the TypedDict.
    """
    type_hints = get_type_hints(td_type)
    required_keys = getattr(td_type, "__required_keys__", set(type_hints.keys()))

    model_fields: dict[str, Any] = {}
    for field_name, field_type in type_hints.items():
        field_info = FieldInfo.from_annotation(field_type)

        if field_name not in required_keys:
            # For optional TypedDict fields, set default=None
            # This makes them not required in the Pydantic model
            # The model should use exclude_unset=True when dumping to get TypedDict semantics
            field_info.default = None

        model_fields[field_name] = (field_info.annotation, field_info)

    return create_model(td_type.__name__, **model_fields, __base__=BaseModel)


def _create_model_from_namedtuple(nt_type: type[Any], globalns: dict[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model from a NamedTuple.

    The created model will have the same name and fields as the NamedTuple.
    """
    type_hints = get_type_hints(nt_type)

    model_fields: dict[str, Any] = {}
    for field_name, field_type in type_hints.items():
        # Skip private fields that NamedTuple adds
        if field_name.startswith("_"):
            continue

        field_info = FieldInfo.from_annotation(field_type)
        model_fields[field_name] = (field_info.annotation, field_info)

    return create_model(nt_type.__name__, **model_fields, __base__=BaseModel)


def _convert_namedtuple_result(result: Any) -> dict[str, Any]:
    return result._asdict()


def _create_wrapped_model(func_name: str, annotation: Any, field_info: FieldInfo) -> type[BaseModel]:
    """Create a model that wraps a type in a 'result' field.

    This is used for primitive types, generic types like list/dict, etc.
    """
    model_name = f"{func_name}Output"

    # Pydantic needs type(None) instead of None for the type annotation
    if annotation is None:
        annotation = type(None)

    return create_model(model_name, result=(annotation, field_info), __base__=BaseModel)


def _convert_wrapped_result(result: Any) -> dict[str, Any]:
    return {"result": result}


def _create_dict_model(func_name: str, dict_annotation: Any) -> type[BaseModel]:
    """Create a RootModel for dict[str, T] types."""

    class DictModel(RootModel[dict_annotation]):
        pass

    # Give it a meaningful name
    DictModel.__name__ = f"{func_name}DictOutput"
    DictModel.__qualname__ = f"{func_name}DictOutput"

    return DictModel


def _get_typed_annotation(annotation: Any, globalns: dict[str, Any]) -> Any:
    def try_eval_type(value: Any, globalns: dict[str, Any], localns: dict[str, Any]) -> tuple[Any, bool]:
        try:
            return eval_type_backport(value, globalns, localns), True
        except NameError:
            return value, False

    if isinstance(annotation, str):
        annotation = ForwardRef(annotation)
        annotation, status = try_eval_type(annotation, globalns, globalns)

        # This check and raise could perhaps be skipped, and we (FastMCP) just call
        # model_rebuild right before using it 🤷
        if status is False:
            raise InvalidSignature(f"Unable to evaluate type annotation {annotation}")

    return annotation


def _get_typed_signature(call: Callable[..., Any]) -> inspect.Signature:
    """Get function signature while evaluating forward references"""
    signature = inspect.signature(call)
    globalns = getattr(call, "__globals__", {})
    typed_params = [
        inspect.Parameter(
            name=param.name,
            kind=param.kind,
            default=param.default,
            annotation=_get_typed_annotation(param.annotation, globalns),
        )
        for param in signature.parameters.values()
    ]
    typed_return = _get_typed_annotation(signature.return_annotation, globalns)
    typed_signature = inspect.Signature(typed_params, return_annotation=typed_return)
    return typed_signature
