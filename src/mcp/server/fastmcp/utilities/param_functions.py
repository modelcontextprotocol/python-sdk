from collections.abc import Callable
from typing import Annotated, Any

from pydantic.version import VERSION as PYDANTIC_VERSION
from typing_extensions import Doc, deprecated

from mcp.server.fastmcp.utilities import params

PYDANTIC_VERSION_MINOR_TUPLE = tuple(int(x) for x in PYDANTIC_VERSION.split(".")[:2])
PYDANTIC_V2 = PYDANTIC_VERSION_MINOR_TUPLE[0] == 2

if not PYDANTIC_V2:
    from pydantic.fields import Undefined  # type: ignore[attr-defined]
else:
    from pydantic.v1.fields import Undefined

# difference between not given not needed, not given maybe needed.
_Unset: Any = Undefined  # type: ignore


def Path(  # noqa: PLR0913
    default: Annotated[
        Any,
        Doc(
            """
            Default value if the parameter field is not set.

            This doesn't affect `Path` parameters as the value is always required.
            The parameter is available only for compatibility.
            """
        ),
    ] = ...,
    *,
    default_factory: Annotated[
        Callable[[], Any] | None,
        Doc(
            """
            A callable to generate the default value.

            This doesn't affect `Path` parameters as the value is always required.
            The parameter is available only for compatibility.
            """
        ),
    ] = _Unset,
    alias: Annotated[
        str | None,
        Doc(
            """
            An alternative name for the parameter field.

            This will be used to extract the data and for the generated OpenAPI.
            It is particularly useful when you can't use the name you want because it
            is a Python reserved keyword or similar.
            """
        ),
    ] = None,
    alias_priority: Annotated[
        int | None,
        Doc(
            """
            Priority of the alias. This affects whether an alias generator is used.
            """
        ),
    ] = None,
    validation_alias: Annotated[
        str | None,
        Doc(
            """
            'Whitelist' validation step. The parameter field will be the single one
            allowed by the alias or set of aliases defined.
            """
        ),
    ] = None,
    serialization_alias: Annotated[
        str | None,
        Doc(
            """
            'Blacklist' validation step. The vanilla parameter field will be the
            single one of the alias' or set of aliases' fields and all the other
            fields will be ignored at serialization time.
            """
        ),
    ] = None,
    title: Annotated[
        str | None,
        Doc(
            """
            Human-readable title.
            """
        ),
    ] = None,
    description: Annotated[
        str | None,
        Doc(
            """
            Human-readable description.
            """
        ),
    ] = None,
    gt: Annotated[
        float | None,
        Doc(
            """
            Greater than. If set, value must be greater than this. Only applicable to
            numbers.
            """
        ),
    ] = None,
    ge: Annotated[
        float | None,
        Doc(
            """
            Greater than or equal. If set, value must be greater than or equal to
            this. Only applicable to numbers.
            """
        ),
    ] = None,
    lt: Annotated[
        float | None,
        Doc(
            """
            Less than. If set, value must be less than this. Only applicable to numbers.
            """
        ),
    ] = None,
    le: Annotated[
        float | None,
        Doc(
            """
            Less than or equal. If set, value must be less than or equal to this.
            Only applicable to numbers.
            """
        ),
    ] = None,
    min_length: Annotated[
        int | None,
        Doc(
            """
            Minimum length for strings.
            """
        ),
    ] = None,
    max_length: Annotated[
        int | None,
        Doc(
            """
            Maximum length for strings.
            """
        ),
    ] = None,
    pattern: Annotated[
        str | None,
        Doc(
            """
            RegEx pattern for strings.
            """
        ),
    ] = None,
    discriminator: Annotated[
        str | None,
        Doc(
            """
            Parameter field name for discriminating the type in a tagged union.
            """
        ),
    ] = None,
    strict: Annotated[
        bool | None,
        Doc(
            """
            If `True`, strict validation is applied to the field.
            """
        ),
    ] = None,
    multiple_of: Annotated[
        float | None,
        Doc(
            """
            Value must be a multiple of this. Only applicable to numbers.
            """
        ),
    ] = None,
    allow_inf_nan: Annotated[
        bool | None,
        Doc(
            """
            Allow `inf`, `-inf`, `nan`. Only applicable to numbers.
            """
        ),
    ] = None,
    max_digits: Annotated[
        int | None,
        Doc(
            """
            Maximum number of allow digits for strings.
            """
        ),
    ] = None,
    decimal_places: Annotated[
        int | None,
        Doc(
            """
            Maximum number of decimal places allowed for numbers.
            """
        ),
    ] = None,
    examples: Annotated[
        list[Any] | None,
        Doc(
            """
            Example values for this field.
            """
        ),
    ] = None,
    include_in_schema: Annotated[
        bool,
        Doc(
            """
            To include (or not) this parameter field in the generated OpenAPI.
            You probably don't need it, but it's available.

            This affects the generated OpenAPI (e.g. visible at `/docs`).
            """
        ),
    ] = True,
    json_schema_extra: Annotated[
        dict[str, Any] | None,
        Doc(
            """
            Any additional JSON schema data.
            """
        ),
    ] = None,
) -> Any:
    """
    Declare a path parameter for a *path operation*.
    """
    return params.Path(
        default=default,
        default_factory=default_factory,
        alias=alias,
        alias_priority=alias_priority,
        validation_alias=validation_alias,
        serialization_alias=serialization_alias,
        title=title,
        description=description,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        min_length=min_length,
        max_length=max_length,
        pattern=pattern,
        discriminator=discriminator,
        strict=strict,
        multiple_of=multiple_of,
        allow_inf_nan=allow_inf_nan,
        max_digits=max_digits,
        decimal_places=decimal_places,
        examples=examples,
        deprecated=deprecated,  # type: ignore
        include_in_schema=include_in_schema,
        json_schema_extra=json_schema_extra,
    )


def Query(  # noqa: PLR0913
    default: Annotated[
        Any,
        Doc(
            """
            Default value if the parameter field is not set.
            """
        ),
    ] = Undefined,
    *,
    default_factory: Annotated[
        Callable[[], Any] | None,
        Doc(
            """
            A callable to generate the default value.

            This doesn't affect `Path` parameters as the value is always required.
            The parameter is available only for compatibility.
            """
        ),
    ] = _Unset,
    alias: Annotated[
        str | None,
        Doc(
            """
            An alternative name for the parameter field.

            This will be used to extract the data and for the generated OpenAPI.
            It is particularly useful when you can't use the name you want because it
            is a Python reserved keyword or similar.
            """
        ),
    ] = None,
    alias_priority: Annotated[
        int | None,
        Doc(
            """
            Priority of the alias. This affects whether an alias generator is used.
            """
        ),
    ] = _Unset,
    validation_alias: Annotated[
        str | None,
        Doc(
            """
            'Whitelist' validation step. The parameter field will be the single one
            allowed by the alias or set of aliases defined.
            """
        ),
    ] = None,
    serialization_alias: Annotated[
        str | None,
        Doc(
            """
            'Blacklist' validation step. The vanilla parameter field will be the
            single one of the alias' or set of aliases' fields and all the other
            fields will be ignored at serialization time.
            """
        ),
    ] = None,
    title: Annotated[
        str | None,
        Doc(
            """
            Human-readable title.
            """
        ),
    ] = None,
    description: Annotated[
        str | None,
        Doc(
            """
            Human-readable description.
            """
        ),
    ] = None,
    gt: Annotated[
        float | None,
        Doc(
            """
            Greater than. If set, value must be greater than this. Only applicable to
            numbers.
            """
        ),
    ] = None,
    ge: Annotated[
        float | None,
        Doc(
            """
            Greater than or equal. If set, value must be greater than or equal to
            this. Only applicable to numbers.
            """
        ),
    ] = None,
    lt: Annotated[
        float | None,
        Doc(
            """
            Less than. If set, value must be less than this. Only applicable to numbers.
            """
        ),
    ] = None,
    le: Annotated[
        float | None,
        Doc(
            """
            Less than or equal. If set, value must be less than or equal to this.
            Only applicable to numbers.
            """
        ),
    ] = None,
    min_length: Annotated[
        int | None,
        Doc(
            """
            Minimum length for strings.
            """
        ),
    ] = None,
    max_length: Annotated[
        int | None,
        Doc(
            """
            Maximum length for strings.
            """
        ),
    ] = None,
    pattern: Annotated[
        str | None,
        Doc(
            """
            RegEx pattern for strings.
            """
        ),
    ] = None,
    discriminator: Annotated[
        str | None,
        Doc(
            """
            Parameter field name for discriminating the type in a tagged union.
            """
        ),
    ] = None,
    strict: Annotated[
        bool | None,
        Doc(
            """
            If `True`, strict validation is applied to the field.
            """
        ),
    ] = _Unset,
    multiple_of: Annotated[
        float | None,
        Doc(
            """
            Value must be a multiple of this. Only applicable to numbers.
            """
        ),
    ] = _Unset,
    allow_inf_nan: Annotated[
        bool | None,
        Doc(
            """
            Allow `inf`, `-inf`, `nan`. Only applicable to numbers.
            """
        ),
    ] = _Unset,
    max_digits: Annotated[
        int | None,
        Doc(
            """
            Maximum number of allow digits for strings.
            """
        ),
    ] = _Unset,
    decimal_places: Annotated[
        int | None,
        Doc(
            """
            Maximum number of decimal places allowed for numbers.
            """
        ),
    ] = _Unset,
    examples: Annotated[
        list[Any] | None,
        Doc(
            """
            Example values for this field.
            """
        ),
    ] = None,
    deprecated: Annotated[
        deprecated | str | bool | None,
        Doc(
            """
            Mark this parameter field as deprecated.

            It will affect the generated OpenAPI (e.g. visible at `/docs`).
            """
        ),
    ] = None,
    include_in_schema: Annotated[
        bool,
        Doc(
            """
            To include (or not) this parameter field in the generated OpenAPI.
            You probably don't need it, but it's available.

            This affects the generated OpenAPI (e.g. visible at `/docs`).
            """
        ),
    ] = True,
    json_schema_extra: Annotated[
        dict[str, Any] | None,
        Doc(
            """
            Any additional JSON schema data.
            """
        ),
    ] = None,
    **extra: Annotated[
        Any,
        Doc(
            """
            Include extra fields used by the JSON Schema.
            """
        ),
        deprecated(
            """
            The `extra` kwargs is deprecated. Use `json_schema_extra` instead.
            """
        ),
    ],
) -> Any:
    return params.Query(
        default=default,
        default_factory=default_factory,
        alias=alias,
        alias_priority=alias_priority,
        validation_alias=validation_alias,
        serialization_alias=serialization_alias,
        title=title,
        description=description,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        min_length=min_length,
        max_length=max_length,
        pattern=pattern,
        discriminator=discriminator,
        strict=strict,
        multiple_of=multiple_of,
        allow_inf_nan=allow_inf_nan,
        max_digits=max_digits,
        decimal_places=decimal_places,
        examples=examples,
        deprecated=deprecated,
        include_in_schema=include_in_schema,
        json_schema_extra=json_schema_extra,
        **extra,
    )
