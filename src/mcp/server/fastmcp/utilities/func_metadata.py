import functools
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import (
    Annotated,
    Any,
    ForwardRef,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    WithJsonSchema,
    create_model,
)
from pydantic._internal._typing_extra import eval_type_backport
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from mcp.server.fastmcp.exceptions import InvalidSignature
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


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


def func_metadata(func: Callable[..., Any], skip_names: Sequence[str] = ()) -> FuncMetadata:
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
    resp = FuncMetadata(arg_model=arguments_model)
    return resp


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
    typed_signature = inspect.Signature(typed_params)
    return typed_signature


def use_defaults_on_optional_validation_error(
    decorated_fn: Callable[..., Any],
) -> Callable[..., Any]:
    """
    Decorator for a function already wrapped by pydantic.validate_call.
    If the wrapped function call fails due to a ValidationError, this decorator
    checks if the error was caused by an optional parameter. If so, it retries
    the call, explicitly omitting the failing optional parameter(s) to allow
    Pydantic/the function to use their default values.

    If the error is for a required parameter, or if the retry fails, the original
    error is re-raised.
    """
    # Get the original function's signature (before validate_call) to inspect defaults
    original_fn = inspect.unwrap(decorated_fn)
    original_sig = inspect.signature(original_fn)
    optional_params_with_defaults = {
        name: param.default
        for name, param in original_sig.parameters.items()
        if param.default is not inspect.Parameter.empty
    }

    @functools.wraps(decorated_fn)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await decorated_fn(*args, **kwargs)
        except ValidationError as e:
            # Check if the validation error is solely for optional parameters
            failing_optional_params_to_retry: dict[str, bool] = {}
            failing_required_params: list[str] = []  # Explicitly typed

            for error in e.errors():
                # error['loc'] is a tuple, e.g., ('param_name',)
                # Pydantic error locations are tuples of strings or ints.
                # For field errors, the first element is the field name (str).
                if error["loc"] and isinstance(error["loc"][0], str):
                    param_name: str = error["loc"][0]
                    if param_name in optional_params_with_defaults:
                        # It's an optional param that failed. Mark for retry by exclude.
                        failing_optional_params_to_retry[param_name] = True
                    else:
                        # It's a required parameter or a non-parameter error
                        failing_required_params.append(param_name)
                else:  # Non-parameter specific error or unexpected error structure
                    raise e

            if failing_required_params or not failing_optional_params_to_retry:
                # re-raise if any req params failed, or if no opt params were identified
                logger.debug(
                    f"Validation failed for required params or no optional params "
                    f"identified. Re-raising original error for {original_fn.__name__}."
                )
                raise e

            # At this point, only optional parameters caused the ValidationError.
            # Retry the call, removing the failing optional params from kwargs.
            # This allows validate_call/the function to use their defaults.
            new_kwargs = {k: v for k, v in kwargs.items() if k not in failing_optional_params_to_retry}

            # Preserve positional arguments
            # failing_optional_params_to_retry.keys() is a KeysView[str]
            # list(KeysView[str]) is list[str]
            logger.info(
                f"Retrying {original_fn.__name__} with default values"
                f"for optional params: {list(failing_optional_params_to_retry.keys())}"
            )
            return await decorated_fn(*args, **new_kwargs)

    @functools.wraps(decorated_fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return decorated_fn(*args, **kwargs)
        except ValidationError as e:
            failing_optional_params_to_retry: dict[str, bool] = {}
            failing_required_params: list[str] = []  # Explicitly typed

            for error in e.errors():
                if error["loc"] and isinstance(error["loc"][0], str):
                    param_name: str = error["loc"][0]
                    if param_name in optional_params_with_defaults:
                        failing_optional_params_to_retry[param_name] = True
                    else:
                        failing_required_params.append(param_name)
                else:
                    raise e

            if failing_required_params or not failing_optional_params_to_retry:
                logger.debug(
                    f"Validation failed for required params or no optional params "
                    f"identified. Re-raising original error for {original_fn.__name__}."
                )
                raise e

            new_kwargs = {k: v for k, v in kwargs.items() if k not in failing_optional_params_to_retry}
            logger.info(
                f"Retrying {original_fn.__name__} with default values"
                f"for optional params: {list(failing_optional_params_to_retry.keys())}"
            )
            return decorated_fn(*args, **new_kwargs)

    if inspect.iscoroutinefunction(
        original_fn
    ):  # Check original_fn because decorated_fn might be a partial or already wrapped
        return async_wrapper
    return sync_wrapper
