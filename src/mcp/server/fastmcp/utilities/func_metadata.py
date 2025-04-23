import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import (
    Annotated,
    Any,
    ForwardRef,
)

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, create_model
from pydantic._internal._typing_extra import eval_type_backport
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from mcp.server.fastmcp.exceptions import InvalidSignature
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class ClientProvidedArg:
    """A class to annotate an argument that is to be provided by client at call
    time and to be skipped from JSON schema generation."""

    def __init__(self):
        pass


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


def filter_args_by_arg_model(
    arguments: dict[str, Any], model_filter: type[ArgModelBase] | None = None
) -> dict[str, Any]:
    """Filter the arguments dictionary to only include keys that are present in
    `model_filter`."""
    if not model_filter:
        return arguments
    filtered_args: dict[str, Any] = {}
    for key in arguments.keys():
        if key in model_filter.model_fields.keys():
            filtered_args[key] = arguments[key]
    return filtered_args


class FuncMetadata(BaseModel):
    """Metadata about a function, including Pydantic models for argument validation.

    This class manages the arguments required by a function, separating them into two 
    categories:

    *   `arg_model`: A Pydantic model representing the function's standard arguments. 
        These arguments will be included in the JSON schema when the tool is listed, 
        allowing for automatic argument parsing. This defines the structure of the 
        expected input.

    *   `client_provided_arg_model` (Optional): A Pydantic model representing arguments 
        that need to be provided directly by the client and will not be included in the 
        JSON schema. 

    """

    arg_model: Annotated[type[ArgModelBase], WithJsonSchema(None)]
    client_provided_arg_model: (
        Annotated[type[ArgModelBase], WithJsonSchema(None)] | None
    ) = None

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
    func: Callable[..., Any], skip_names: Sequence[str] = ()
) -> FuncMetadata:
    """Given a function, return metadata including a pydantic model representing its
    signature.

    The use case for this is
    ```
    meta = func_to_pyd(func)
    validated_args = meta.arg_model.model_validate(some_raw_data_dict)
    return func(**validated_args.model_dump_one_level())
    ```

    **critically** it also provides pre-parse helper to attempt to parse things from
    JSON.

    Args:
        func: The function to convert to a pydantic model
        skip_names: A list of parameter names to skip. These will not be included in
            the model.
    Returns:
        A pydantic model representing the function's signature.
    """
    sig = _get_typed_signature(func)
    params = sig.parameters
    dynamic_pydantic_arg_model_params: dict[str, Any] = {}
    dynamic_pydantic_client_provided_arg_model_params: dict[str, Any] = {}
    globalns = getattr(func, "__globals__", {})
    for param in params.values():
        if param.name.startswith("_"):
            raise InvalidSignature(
                f"Parameter {param.name} of {func.__name__} cannot start with '_'"
            )
        if param.name in skip_names:
            continue
        annotation = param.annotation

        # `x: None` / `x: None = None`
        if annotation is None:
            annotation = Annotated[
                None,
                Field(
                    default=param.default
                    if param.default is not inspect.Parameter.empty
                    else PydanticUndefined
                ),
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
            param.default
            if param.default is not inspect.Parameter.empty
            else PydanticUndefined,
        )

        # loop through annotations,
        # use ClientProvidedArg metadata to split the arguments
        if any(isinstance(m, ClientProvidedArg) for m in field_info.metadata):
            dynamic_pydantic_client_provided_arg_model_params[param.name] = (
                field_info.annotation,
                field_info,
            )
        else:
            dynamic_pydantic_arg_model_params[param.name] = (
                field_info.annotation,
                field_info,
            )

    arguments_model = create_model(
        f"{func.__name__}Arguments",
        **dynamic_pydantic_arg_model_params,
        __base__=ArgModelBase,
    )

    provided_arguments_model = create_model(
        f"{func.__name__}ClientProvidedArguments",
        **dynamic_pydantic_client_provided_arg_model_params,
        __base__=ArgModelBase,
    )
    resp = FuncMetadata(
        arg_model=arguments_model, client_provided_arg_model=provided_arguments_model
    )
    return resp


def _get_typed_annotation(annotation: Any, globalns: dict[str, Any]) -> Any:
    def try_eval_type(
        value: Any, globalns: dict[str, Any], localns: dict[str, Any]
    ) -> tuple[Any, bool]:
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
    typed_signature = inspect.Signature(typed_params)
    return typed_signature
