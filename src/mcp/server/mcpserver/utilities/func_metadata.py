import functools
import inspect
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from itertools import chain
from types import GenericAlias
from typing import Annotated, Any, Union, cast, get_args, get_origin

import anyio
import anyio.to_thread
import pydantic_core
from mcp_types import CallToolResult, ContentBlock, InputRequiredResult, TextContent
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    PydanticUserError,
    TypeAdapter,
    WithJsonSchema,
    create_model,
)
from pydantic.fields import FieldInfo
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaWarningKind
from typing_extensions import NotRequired, ReadOnly, TypedDict, deprecated, get_type_hints, is_typeddict
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
from mcp.shared.exceptions import MCPDeprecationWarning

logger = get_logger(__name__)


def _is_input_required_type(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, InputRequiredResult)


_CONTENT_TYPES = (*get_args(ContentBlock), Image, Audio)
# `_convert_to_content` unrolls list/tuple values; a `Sequence[...]` annotation is one of those at runtime.
_CONTENT_SEQUENCE_ORIGINS = (list, tuple, Sequence)


def _returns_content(annotation: Any) -> bool:
    """Whether a return annotation declares content blocks or the `Image`/`Audio` helpers, bare or as
    the items of a list/tuple or the arms of a union: the values `_convert_to_content` renders as blocks
    rather than dumping as data. Keep the two in sync."""
    origin = get_origin(annotation)
    if origin is None:
        return isinstance(annotation, type) and issubclass(annotation, _CONTENT_TYPES)
    if origin is Annotated:
        return _returns_content(get_args(annotation)[0])
    if is_union_origin(origin) or origin in _CONTENT_SEQUENCE_ORIGINS:
        return any(_returns_content(arg) for arg in get_args(annotation))
    return False


class StrictJsonSchema(GenerateJsonSchema):
    """A JSON schema generator that raises exceptions instead of emitting warnings.

    This is used to detect non-serializable types during schema generation.
    """

    def emit_warning(self, kind: JsonSchemaWarningKind, detail: str) -> None:
        # Raise an exception instead of emitting a warning
        raise ValueError(f"JSON schema warning: {kind} - {detail}")


_LOCAL_DEFS_PREFIX = "#/$defs/"


def _inline_root_ref(schema: dict[str, Any]) -> dict[str, Any]:
    """Give a schema whose root is a bare `$ref` into `$defs` an inline root.

    pydantic emits a self-referential model as `{"$defs": {...}, "$ref": "#/$defs/Model"}`, with no
    `type` at the root; `Tool.outputSchema` needs an object root (required on the wire through
    2025-11-25). The referenced definition is copied onto the root and `$defs` is kept, since nested
    references still point into it. Root siblings of the `$ref` win over the definition's keys.
    """
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith(_LOCAL_DEFS_PREFIX):
        return schema
    definition = cast(dict[str, Any], schema["$defs"][ref.removeprefix(_LOCAL_DEFS_PREFIX)])
    siblings = {key: value for key, value in schema.items() if key != "$ref"}
    return {**definition, **siblings}


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
    """A tool function's argument model plus, for structured output, the published `output_schema` and the
    `output_model` results are validated against. Constructing one with an `output_model` and no schema derives
    the schema (and raises if pydantic can't); the fields are read live, so clearing or reassigning them later
    takes effect on the next call."""

    arg_model: Annotated[type[ArgModelBase], WithJsonSchema(None)]
    output_schema: dict[str, Any] | None = None
    output_model: Annotated[type[Any], WithJsonSchema(None)] | None = None
    wrap_output: bool = False
    _adapter: tuple[type[Any], TypeAdapter[Any]] | None = PrivateAttr(default=None)

    def model_post_init(self, context: Any, /) -> None:
        if self.output_model is not None and self.output_schema is None:
            # StrictJsonSchema raises instead of warning, so an unserializable return type fails construction.
            schema = self._output_adapter(self.output_model).json_schema(schema_generator=StrictJsonSchema)
            self.output_schema = _inline_root_ref(schema)

    def _output_adapter(self, output_model: type[Any]) -> TypeAdapter[Any]:
        """The validator/serializer for `output_model`, built once and rebuilt only if the field is reassigned."""
        if self._adapter is None or self._adapter[0] is not output_model:
            self._adapter = (output_model, TypeAdapter(_pydantic_readable_typeddict(output_model)))
        return self._adapter[1]

    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        """Validate raw arguments into a one-level kwargs dict (no function call).

        Used to feed resolver dependency injection the validated tool arguments
        before the tool function itself runs.
        """
        arguments_pre_parsed = self.pre_parse_json(arguments_to_validate)
        arguments_parsed_model = self.arg_model.model_validate(arguments_pre_parsed)
        return arguments_parsed_model.model_dump_one_level()

    async def call_fn(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        fn_is_async: bool,
        arguments: dict[str, Any],
        arguments_to_pass_directly: dict[str, Any] | None = None,
    ) -> Any:
        """Call the function with already-validated `arguments` plus `arguments_to_pass_directly`.

        `arguments` is the output of `validate_arguments`. A sync function runs on a
        worker thread.
        """
        kwargs = arguments | (arguments_to_pass_directly or {})
        if fn_is_async:
            return await fn(**kwargs)
        return await anyio.to_thread.run_sync(functools.partial(fn, **kwargs))

    @deprecated(
        "FuncMetadata.call_fn_with_arg_validation() is deprecated and will be removed in 3.0; "
        "call validate_arguments() and then call_fn() instead.",
        category=MCPDeprecationWarning,
    )
    async def call_fn_with_arg_validation(
        self,
        fn: Callable[..., Any | Awaitable[Any]],
        fn_is_async: bool,
        arguments_to_validate: dict[str, Any],
        arguments_to_pass_directly: dict[str, Any] | None,
        pre_validated: dict[str, Any] | None = None,
    ) -> Any:
        """Validate `arguments_to_validate` (unless `pre_validated` is given) and call the function.

        Deprecated: call `validate_arguments` and then `call_fn`.
        """
        arguments = pre_validated if pre_validated is not None else self.validate_arguments(arguments_to_validate)
        return await self.call_fn(fn, fn_is_async, arguments, arguments_to_pass_directly)

    def convert_result(self, result: Any) -> CallToolResult | InputRequiredResult:
        """Convert a function call result into a `CallToolResult`.

        An `InputRequiredResult` is passed through unchanged so the multi-round
        flow surfaces on the wire as `resultType: "input_required"` rather than
        being JSON-dumped into a text block.

        Note: we build unstructured content here **even though the lowlevel server
        tool call handler provides generic backwards compatibility serialization of
        structured content**. This is for MCPServer backwards compatibility: we need to
        retain MCPServer's ad hoc conversion logic for constructing unstructured output
        from function return values, whereas the lowlevel server simply serializes
        the structured output.
        """
        if isinstance(result, InputRequiredResult):
            return result
        # A schema published without a model (hand-built metadata) is advertised but not validated here.
        output_model = self.output_model if self.output_schema is not None else None
        if isinstance(result, CallToolResult):
            if output_model is not None and not result.is_error:
                self._output_adapter(output_model).validate_python(result.structured_content)
            return result

        unstructured_content = _convert_to_content(result)

        if output_model is None:
            return CallToolResult(content=unstructured_content)

        if self.wrap_output:
            result = {"result": result}

        # The tool hands back Python-side names; the wire (and outputSchema) use aliases.
        adapter = self._output_adapter(output_model)
        validated = adapter.validate_python(result, by_alias=True, by_name=True)
        if isinstance(validated, BaseModel):
            # Dump via the instance so a returned subclass keeps its own fields.
            structured_content = validated.model_dump(mode="json", by_alias=True)
        else:
            structured_content = adapter.dump_python(validated, mode="json", by_alias=True)

        return CallToolResult(content=unstructured_content, structured_content=structured_content)

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
            if data_key not in key_to_field_info:
                continue

            field_info = key_to_field_info[data_key]
            if isinstance(data_value, str) and field_info.annotation is not str:
                try:
                    pre_parsed = json.loads(data_value)
                except (ValueError, RecursionError):
                    # Not JSON, or JSON the parser refuses (over-long integers, deep
                    # nesting): leave the string for validation to accept or reject.
                    continue
                if isinstance(pre_parsed, str | int | float):
                    # This is likely that the raw value is e.g. `"hello"` which we
                    # Should really be parsed as '"hello"' in Python - but if we parse
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
            - TypedDict - used directly
            - Dataclasses and other annotated classes - converted to Pydantic models
            - Generic types (list, dict, Union, etc.) - wrapped in a model with a 'result' field
            - Content blocks (TextContent, EmbeddedResource, ...), Image and Audio, bare or inside a
                list, tuple or union - unstructured when auto-detecting; structured_output=True bypasses
                this rule (a content block then publishes its own schema; Image/Audio have none and raise)

    Returns:
        A FuncMetadata object containing:
        - arg_model: A Pydantic model representing the function's arguments
        - output_schema: The published JSON schema for structured output, or None if the output is unstructured
        - output_model: The type structured output is validated against: the declared BaseModel or TypedDict,
            or a synthesized model for wrapped, `dict[str, T]` and annotated-class returns
        - wrap_output: Whether the function result needs to be wrapped in `{"result": ...}` for structured output.
    """
    try:
        sig = inspect.signature(func, eval_str=True)
    except NameError as e:  # pragma: no cover
        # This raise could perhaps be skipped, and we (MCPServer) just call
        # model_rebuild right before using it 🤷
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

    arguments_model = create_model(
        f"{func.__name__}Arguments",
        __base__=ArgModelBase,
        **dynamic_pydantic_model_params,
    )

    if structured_output is False:
        return FuncMetadata(arg_model=arguments_model)

    # set up structured output support based on return type annotation

    if sig.return_annotation is inspect.Parameter.empty and structured_output is True:
        raise InvalidSignature(f"Function {func.__name__}: return annotation required for structured output")

    try:
        inspected_return_ann = inspect_annotation(sig.return_annotation, annotation_source=AnnotationSource.FUNCTION)
    except ForbiddenQualifier as e:
        raise InvalidSignature(f"Function {func.__name__}: return annotation contains an invalid type qualifier") from e

    return_type_expr = inspected_return_ann.type

    # `AnnotationSource.FUNCTION` allows no type qualifier to be used, so `return_type_expr` is guaranteed to *not* be
    # unknown (i.e. a bare `Final`).
    assert return_type_expr is not UNKNOWN

    if _is_input_required_type(return_type_expr):
        # A tool annotated to return only InputRequiredResult never produces structured content.
        return FuncMetadata(arg_model=arguments_model)

    # The annotation fed to schema derivation. Starts as the raw return annotation (preserving any
    # Annotated[...] wrapper) and is narrowed below if InputRequiredResult arms are stripped.
    effective_annotation: Any = sig.return_annotation

    if is_union_origin(get_origin(return_type_expr)):
        args = get_args(return_type_expr)
        # InputRequiredResult is a control-flow signal, not data: strip it so the residual arms
        # drive schema derivation. convert_result short-circuits on an InputRequiredResult instance
        # before output validation, so the schema only ever sees the data arms at runtime.
        residual = tuple(a for a in args if not _is_input_required_type(a))
        if not residual:
            return FuncMetadata(arg_model=arguments_model)
        if len(residual) != len(args):
            # PEP 604 has no syntax for "union of a runtime tuple"; Union[...] is the only spelling.
            effective_annotation = residual[0] if len(residual) == 1 else Union[residual]  # noqa: UP007
            # Re-normalize so the residual is processed exactly as if it had been the declared
            # return annotation: unwraps a top-level Annotated[...] arm and re-derives metadata,
            # so the CallToolResult/BaseModel/TypedDict dispatch below sees the bare type.
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
            return FuncMetadata(arg_model=arguments_model)
    else:
        original_annotation = effective_annotation

    if structured_output is None and _returns_content(return_type_expr):
        # Content blocks and the Image/Audio helpers are what the model reads, not data for the
        # application: a derived schema would advertise the block's own model as output_schema (and,
        # unless the tool builds its own CallToolResult, echo every block into structured_content).
        # structured_output=True still forces one.
        return FuncMetadata(arg_model=arguments_model)

    output_model, wrap_output = _create_output_model(original_annotation, return_type_expr, func.__name__)

    if output_model is not None:
        try:
            # FuncMetadata builds the validator and schema on construction, so an unsupported return type
            # surfaces here, at registration, rather than on the first call.
            return FuncMetadata(arg_model=arguments_model, output_model=output_model, wrap_output=wrap_output)
        except (
            PydanticUserError,
            ForbiddenQualifier,
            NameError,
            TypeError,
            ValueError,
            pydantic_core.SchemaError,
            pydantic_core.ValidationError,
        ) as e:
            # These are expected errors when a type can't be converted to a Pydantic schema
            # PydanticUserError: When Pydantic can't handle the type (e.g. PydanticInvalidForJsonSchema);
            #   subclasses TypeError on pydantic <2.13 and RuntimeError on pydantic >=2.13
            # ForbiddenQualifier, NameError: an invalid qualifier or unresolvable annotation on a TypedDict key,
            #   met while rebuilding a stdlib TypedDict below 3.12 (pydantic reports both as PydanticUserError)
            # ValueError: When there are issues with the type definition (including our custom warnings);
            #   arrives wrapped in a ValidationError when raised during FuncMetadata construction
            # SchemaError: When Pydantic can't build a schema
            # ValidationError: When validation fails
            logger.info(f"Cannot create schema for type {return_type_expr} in {func.__name__}: {type(e).__name__}: {e}")

    if structured_output is True:
        # Model creation failed or produced warnings - no structured output
        raise InvalidSignature(
            f"Function {func.__name__}: return type {return_type_expr} is not serializable for structured output"
        )

    return FuncMetadata(arg_model=arguments_model)


def _create_output_model(original_annotation: Any, type_expr: Any, func_name: str) -> tuple[type[Any] | None, bool]:
    """Pick the type structured output is validated against for the given return annotation.

    Args:
        original_annotation: The original return annotation (may be wrapped in `Annotated`).
        type_expr: The underlying type expression derived from the return annotation
            (`Annotated` and type qualifiers were stripped).
        func_name: The name of the function.

    Returns:
        tuple of (model or None, wrap_output)
        Model is None if the type cannot carry structured output.
        wrap_output is True if the result needs to be wrapped in {"result": ...}
    """
    model: type[Any] | None = None
    wrap_output = False

    # First handle special case: None
    if type_expr is None:
        model = _create_wrapped_model(func_name, original_annotation)
        wrap_output = True

    # Handle GenericAlias types (list[str], dict[str, int], Union[str, int], etc.)
    elif isinstance(type_expr, GenericAlias):
        origin = get_origin(type_expr)

        # Special case: dict with string keys can use RootModel
        if origin is dict:
            args = get_args(type_expr)
            if len(args) == 2 and args[0] is str:
                # TODO: should we use the original annotation? We are losing any potential `Annotated`
                # metadata for Pydantic here:
                model = _create_dict_model(func_name, type_expr)
            else:
                # dict with non-str keys needs wrapping
                model = _create_wrapped_model(func_name, original_annotation)
                wrap_output = True
        else:
            # All other generic types need wrapping (list, tuple, Union, Optional, etc.)
            model = _create_wrapped_model(func_name, original_annotation)
            wrap_output = True

    # Handle regular type objects
    elif isinstance(type_expr, type):
        type_annotation = cast(type[Any], type_expr)

        # Case 1: BaseModel subclasses (can be used directly)
        if issubclass(type_annotation, BaseModel):
            model = type_annotation

        # Case 2: TypedDicts (pydantic reads qualifiers, totality, docstring and `Annotated` metadata natively)
        elif is_typeddict(type_annotation):
            model = type_annotation

        # Case 3: Primitive types that need wrapping
        elif type_annotation in (str, int, float, bool, bytes, type(None)):
            model = _create_wrapped_model(func_name, original_annotation)
            wrap_output = True

        # Case 4: Other class types (dataclasses, regular classes with annotations)
        else:
            type_hints = get_type_hints(type_annotation)
            if type_hints:
                # Classes with type hints can be converted to Pydantic models
                model = _create_model_from_class(type_annotation, type_hints)
            # Classes without type hints are not serializable - model remains None

    # Handle any other types not covered above
    else:
        # This includes typing constructs that aren't GenericAlias in Python 3.10
        # (e.g., Union, Optional in some Python versions)
        model = _create_wrapped_model(func_name, original_annotation)
        wrap_output = True

    return model, wrap_output


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


def _pydantic_readable_typeddict(output_model: type[Any]) -> type[Any]:
    """pydantic refuses `typing.TypedDict` below Python 3.12 (it needs `__orig_bases__`); rebuild such a return
    type as an equivalent `typing_extensions.TypedDict` so tool authors don't have to know. Only the class itself
    (its keys, docstring and own config) is rebuilt: stdlib TypedDicts nested inside it, or config inherited from
    one, still need `typing_extensions` there. Delete with 3.11 support."""
    if sys.version_info >= (3, 12) or not is_typeddict(output_model) or type(output_model).__module__ != "typing":
        return output_model
    return _as_typing_extensions_typeddict(output_model)  # pragma: lax no cover


def _as_typing_extensions_typeddict(td_type: type[Any]) -> type[Any]:  # pragma: lax no cover
    items: dict[str, Any] = {}
    for name, hint in get_type_hints(td_type, include_extras=True).items():
        key = inspect_annotation(hint, annotation_source=AnnotationSource.TYPED_DICT)
        item: Any = Annotated[(key.type, *key.metadata)] if key.metadata else key.type
        if "read_only" in key.qualifiers:
            item = ReadOnly[item]
        # pydantic's rule: an explicit qualifier wins over class totality. Needed because a stdlib TypedDict
        # this old computes `__required_keys__` without seeing `typing_extensions` qualifiers.
        required = (name in td_type.__required_keys__ or "required" in key.qualifiers) and (
            "not_required" not in key.qualifiers
        )
        items[name] = item if required else NotRequired[item]
    # The functional form, spelled so type checkers don't try to evaluate it statically.
    rebuilt = cast("Callable[[str, dict[str, Any]], type[Any]]", TypedDict)(td_type.__name__, items)
    for attr in ("__doc__", "__module__", "__qualname__", "__pydantic_config__"):
        if hasattr(td_type, attr):
            setattr(rebuilt, attr, getattr(td_type, attr))
    return rebuilt


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


def _convert_to_content(result: Any) -> list[ContentBlock]:
    """Convert a result to a sequence of content objects.

    Note: This conversion logic comes from previous versions of MCPServer and is being
    retained for purposes of backwards compatibility. It produces different unstructured
    output than the lowlevel server tool call handler, which just serializes structured
    content verbatim. `_returns_content` is the annotation-level mirror of these branches.
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
