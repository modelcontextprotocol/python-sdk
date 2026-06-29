import functools
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from itertools import chain
from types import GenericAlias
from typing import Annotated, Any, Union, cast, get_args, get_origin, get_type_hints

import anyio
import anyio.to_thread
import pydantic_core
from mcp_types import CallToolResult, ContentBlock, InputRequiredResult, TextContent
from pydantic import BaseModel, ConfigDict, Field, PydanticUserError, WithJsonSchema, create_model
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

logger = get_logger(__name__)


def _is_input_required_type(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, InputRequiredResult)


class StrictJsonSchema(GenerateJsonSchema):
    """JSON schema generator that raises instead of warning, to detect non-serializable types."""

    def emit_warning(self, kind: JsonSchemaWarningKind, detail: str) -> None:
        raise ValueError(f"JSON schema warning: {kind} - {detail}")


class ArgModelBase(BaseModel):
    """A model representing the arguments to a function."""

    def model_dump_one_level(self) -> dict[str, Any]:
        """Return a dict of the model's fields one level deep; sub-models stay as Pydantic models."""
        kwargs: dict[str, Any] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            value = getattr(self, field_name)
            output_name = field_info.alias if field_info.alias else field_name
            kwargs[output_name] = value
        return kwargs

    model_config = ConfigDict(arbitrary_types_allowed=True)


class FuncMetadata(BaseModel):
    arg_model: Annotated[type[ArgModelBase], WithJsonSchema(None)]
    output_schema: dict[str, Any] | None = None
    output_model: Annotated[type[BaseModel], WithJsonSchema(None)] | None = None
    wrap_output: bool = False

    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        """Validate raw arguments into a one-level kwargs dict, without calling the function.

        Feeds resolver dependency injection the validated tool arguments before the tool runs.
        """
        arguments_pre_parsed = self.pre_parse_json(arguments_to_validate)
        arguments_parsed_model = self.arg_model.model_validate(arguments_pre_parsed)
        return arguments_parsed_model.model_dump_one_level()

    async def call_fn_with_arg_validation(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        fn_is_async: bool,
        arguments_to_validate: dict[str, Any],
        arguments_to_pass_directly: dict[str, Any] | None,
        pre_validated: dict[str, Any] | None = None,
    ) -> Any:
        """Call the given function with arguments validated and injected.

        Pass `pre_validated` (the output of `validate_arguments`) to reuse an earlier validation
        pass - validating twice can re-run `default_factory`/stateful validators and hand the
        function different values than a caller already observed.
        """
        # Copy so a caller-provided `pre_validated` dict is never mutated in place.
        arguments_parsed_dict = dict(
            pre_validated if pre_validated is not None else self.validate_arguments(arguments_to_validate)
        )

        arguments_parsed_dict |= arguments_to_pass_directly or {}

        if fn_is_async:
            return await fn(**arguments_parsed_dict)
        else:
            return await anyio.to_thread.run_sync(functools.partial(fn, **arguments_parsed_dict))

    def convert_result(self, result: Any) -> CallToolResult | InputRequiredResult:
        """Convert a function call result into a `CallToolResult`.

        An `InputRequiredResult` passes through unchanged so the multi-round flow surfaces
        on the wire as `resultType: "input_required"` instead of being JSON-dumped into a
        text block. Unstructured content is built here rather than left to the lowlevel
        server's generic serialization, to retain MCPServer's historical ad hoc conversion
        of function return values.
        """
        if isinstance(result, InputRequiredResult):
            return result
        if isinstance(result, CallToolResult):
            if self.output_schema is not None:
                assert self.output_model is not None, "Output model must be set if output schema is defined"
                self.output_model.model_validate(result.structured_content)
            return result

        unstructured_content = _convert_to_content(result)

        if self.output_schema is None:
            return CallToolResult(content=unstructured_content)

        if self.wrap_output:
            result = {"result": result}

        assert self.output_model is not None, "Output model must be set if output schema is defined"
        validated = self.output_model.model_validate(result)
        structured_content = validated.model_dump(mode="json", by_alias=True)

        return CallToolResult(content=unstructured_content, structured_content=structured_content)

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return `data` with string values parsed as JSON where appropriate.

        Handles clients (notably Claude Desktop) that pass lists and sub-model dicts as
        JSON inside strings, e.g. `'["a", "b", "c"]'` for a list parameter.
        """
        new_data = data.copy()

        key_to_field_info: dict[str, FieldInfo] = {}
        for field_name, field_info in self.arg_model.model_fields.items():
            key_to_field_info[field_name] = field_info
            if field_info.alias:
                key_to_field_info[field_info.alias] = field_info

        for data_key, data_value in data.items():
            if data_key not in key_to_field_info:
                continue

            field_info = key_to_field_info[data_key]
            if isinstance(data_value, str) and field_info.annotation is not str:
                try:
                    pre_parsed = json.loads(data_value)
                except json.JSONDecodeError:
                    continue
                if isinstance(pre_parsed, str | int | float):
                    # A raw value like `"hello"` would lose its quotes if parsed as JSON, so skip it.
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
    """Return metadata for `func`: an argument model, plus an output model/schema when structured.

    For structured output, BaseModel return types are used directly; TypedDicts, dataclasses,
    and other annotated classes are converted to Pydantic models; primitives and generic types
    (list, dict, Union, None, etc.) are wrapped in a model with a `result` field (`wrap_output=True`).

    Args:
        skip_names: Parameter names to exclude from the argument model.
        structured_output: None auto-detects from the return annotation, True requires a
            serializable return annotation, False unconditionally disables structured output.
    """
    try:
        sig = inspect.signature(func, eval_str=True)
    except NameError as e:  # pragma: no cover
        raise InvalidSignature(f"Unable to evaluate type annotations for callable {func.__name__!r}") from e
    params = sig.parameters
    dynamic_pydantic_model_params: dict[str, Any] = {}
    for param in params.values():
        if param.name.startswith("_"):  # pragma: no cover
            raise InvalidSignature(f"Parameter {param.name} of {func.__name__} cannot start with '_'")
        if param.name in skip_names:
            continue

        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
        field_name = param.name
        field_kwargs: dict[str, Any] = {}
        field_metadata: list[Any] = []

        if param.annotation is inspect.Parameter.empty:
            field_metadata.append(WithJsonSchema({"title": param.name, "type": "string"}))
        # Alias params that shadow BaseModel attributes, to avoid Pydantic's shadowing warning.
        if hasattr(BaseModel, field_name) and callable(getattr(BaseModel, field_name)):
            field_kwargs["alias"] = field_name
            field_name = f"field_{field_name}"

        if param.default is not inspect.Parameter.empty:
            dynamic_pydantic_model_params[field_name] = (
                Annotated[(annotation, *field_metadata, Field(**field_kwargs))],
                param.default,
            )
        else:
            dynamic_pydantic_model_params[field_name] = Annotated[(annotation, *field_metadata, Field(**field_kwargs))]

    arguments_model = create_model(
        f"{func.__name__}Arguments",
        __base__=ArgModelBase,
        **dynamic_pydantic_model_params,
    )

    if structured_output is False:
        return FuncMetadata(arg_model=arguments_model)

    if sig.return_annotation is inspect.Parameter.empty and structured_output is True:
        raise InvalidSignature(f"Function {func.__name__}: return annotation required for structured output")

    try:
        inspected_return_ann = inspect_annotation(sig.return_annotation, annotation_source=AnnotationSource.FUNCTION)
    except ForbiddenQualifier as e:
        raise InvalidSignature(f"Function {func.__name__}: return annotation contains an invalid type qualifier") from e

    return_type_expr = inspected_return_ann.type

    # `AnnotationSource.FUNCTION` forbids type qualifiers, so the type is never UNKNOWN (a bare `Final`).
    assert return_type_expr is not UNKNOWN

    if _is_input_required_type(return_type_expr):
        # A tool annotated to return only InputRequiredResult never produces structured content.
        return FuncMetadata(arg_model=arguments_model)

    # The annotation fed to schema derivation; narrowed below if InputRequiredResult arms are stripped.
    effective_annotation: Any = sig.return_annotation

    if is_union_origin(get_origin(return_type_expr)):
        args = get_args(return_type_expr)
        # InputRequiredResult is a control-flow signal, not data: strip it so the residual arms drive
        # schema derivation. convert_result short-circuits on instances before output validation.
        residual = tuple(a for a in args if not _is_input_required_type(a))
        if not residual:
            return FuncMetadata(arg_model=arguments_model)
        if len(residual) != len(args):
            # PEP 604 has no syntax for "union of a runtime tuple"; Union[...] is the only spelling.
            effective_annotation = residual[0] if len(residual) == 1 else Union[residual]  # noqa: UP007
            # Re-inspect so the residual is processed exactly as if declared: unwraps a top-level
            # Annotated[...] arm so the dispatch below sees the bare type.
            inspected_return_ann = inspect_annotation(effective_annotation, annotation_source=AnnotationSource.FUNCTION)
            return_type_expr = inspected_return_ann.type
        if len(residual) > 1 and any(
            isinstance(a, type) and issubclass(a, CallToolResult) for a in residual if a is not type(None)
        ):
            raise InvalidSignature(
                f"Function {func.__name__}: CallToolResult cannot be used in Union or Optional types. "
                "To return empty results, use: CallToolResult(content=[])"
            )

    original_annotation: Any
    # A CallToolResult hint means return-without-validation, unless validation was provided as
    # Annotated metadata.
    if isinstance(return_type_expr, type) and issubclass(return_type_expr, CallToolResult):
        if inspected_return_ann.metadata:
            return_type_expr = inspected_return_ann.metadata[0]
            if len(inspected_return_ann.metadata) >= 2:
                # Preserve remaining metadata: Annotated[CallToolResult, ReturnType, Gt(1)] ->
                # Annotated[ReturnType, Gt(1)].
                original_annotation = Annotated[
                    (return_type_expr, *inspected_return_ann.metadata[1:])
                ]  # pragma: no cover
            else:
                original_annotation = return_type_expr
        else:
            return FuncMetadata(arg_model=arguments_model)
    else:
        original_annotation = effective_annotation

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


def _try_create_model_and_schema(
    original_annotation: Any,
    type_expr: Any,
    func_name: str,
) -> tuple[type[BaseModel] | None, dict[str, Any] | None, bool]:
    """Try to create an output model and schema for the given return annotation.

    `type_expr` is `original_annotation` with `Annotated` wrappers and type qualifiers stripped.

    Returns:
        (model, schema, wrap_output); model and schema are None if schema generation fails or
        warns. wrap_output means the result must be wrapped in `{"result": ...}`.
    """
    model = None
    wrap_output = False

    if type_expr is None:
        model = _create_wrapped_model(func_name, original_annotation)
        wrap_output = True

    elif isinstance(type_expr, GenericAlias):
        origin = get_origin(type_expr)

        if origin is dict:
            args = get_args(type_expr)
            if len(args) == 2 and args[0] is str:
                # TODO: use original_annotation? Any `Annotated` metadata for Pydantic is lost here.
                model = _create_dict_model(func_name, type_expr)
            else:
                model = _create_wrapped_model(func_name, original_annotation)
                wrap_output = True
        else:
            model = _create_wrapped_model(func_name, original_annotation)
            wrap_output = True

    elif isinstance(type_expr, type):
        type_annotation = cast(type[Any], type_expr)

        if issubclass(type_annotation, BaseModel):
            model = type_annotation

        elif is_typeddict(type_annotation):
            model = _create_model_from_typeddict(type_annotation)

        elif type_annotation in (str, int, float, bool, bytes, type(None)):
            model = _create_wrapped_model(func_name, original_annotation)
            wrap_output = True

        else:
            type_hints = get_type_hints(type_annotation)
            if type_hints:
                model = _create_model_from_class(type_annotation, type_hints)
            # Classes without type hints aren't serializable; model stays None.

    else:
        # Typing constructs that aren't GenericAlias on Python 3.10 (e.g. Union, Optional).
        model = _create_wrapped_model(func_name, original_annotation)
        wrap_output = True

    if model:
        try:
            schema = model.model_json_schema(schema_generator=StrictJsonSchema)
        except (
            PydanticUserError,
            TypeError,
            ValueError,
            pydantic_core.SchemaError,
            pydantic_core.ValidationError,
        ) as e:
            # Expected when a type can't become a Pydantic schema; ValueError includes
            # StrictJsonSchema's converted warnings. PydanticUserError subclasses TypeError on
            # pydantic <2.13 and RuntimeError on pydantic >=2.13.
            logger.info(f"Cannot create schema for type {type_expr} in {func_name}: {type(e).__name__}: {e}")
            return None, None, False

        return model, schema, wrap_output

    return None, None, False


_no_default = object()


def _create_model_from_class(cls: type[Any], type_hints: dict[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model mirroring an ordinary class's name and type-hinted fields.

    Precondition: `type_hints` is non-empty.
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
    """Create a Pydantic model with the same name and fields as the TypedDict."""
    type_hints = get_type_hints(td_type)
    required_keys = getattr(td_type, "__required_keys__", set(type_hints.keys()))

    model_fields: dict[str, Any] = {}
    for field_name, field_type in type_hints.items():
        if field_name not in required_keys:
            # Non-required keys default to None; dump with exclude_unset=True for TypedDict semantics.
            model_fields[field_name] = (field_type, None)
        else:
            model_fields[field_name] = field_type

    return create_model(td_type.__name__, **model_fields)


def _create_wrapped_model(func_name: str, annotation: Any) -> type[BaseModel]:
    """Create a model that wraps a type in a `result` field."""
    model_name = f"{func_name}Output"

    return create_model(model_name, result=annotation)


def _create_dict_model(func_name: str, dict_annotation: Any) -> type[BaseModel]:
    """Create a RootModel for dict[str, T] types."""
    # TODO(Marcelo): We should not rely on RootModel for this.
    from pydantic import RootModel  # noqa: TID251

    class DictModel(RootModel[dict_annotation]):
        pass

    DictModel.__name__ = f"{func_name}DictOutput"
    DictModel.__qualname__ = f"{func_name}DictOutput"

    return DictModel


def _convert_to_content(result: Any) -> list[ContentBlock]:
    """Convert a result to a list of content blocks.

    Retained from previous MCPServer versions for backwards compatibility; produces different
    unstructured output than the lowlevel server, which serializes structured content verbatim.
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
