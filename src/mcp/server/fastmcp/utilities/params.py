from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic.fields import FieldInfo
from pydantic.version import VERSION as PYDANTIC_VERSION
from typing_extensions import deprecated

PYDANTIC_VERSION_MINOR_TUPLE = tuple(int(x) for x in PYDANTIC_VERSION.split(".")[:2])
PYDANTIC_V2 = PYDANTIC_VERSION_MINOR_TUPLE[0] == 2

if not PYDANTIC_V2:
    from pydantic.fields import Undefined  # type: ignore[attr-defined]
else:
    from pydantic.v1.fields import Undefined

# difference between not given not needed, not given maybe needed.
_Unset: Any = Undefined  # type: ignore


class ParamTypes(Enum):
    query = "query"
    path = "path"


class Param(FieldInfo):  # type: ignore[misc]
    in_: ParamTypes

    def __init__(  # noqa: PLR0913
        self,
        default: Any = Undefined,
        *,
        default_factory: Callable[[], Any] | None = _Unset,
        annotation: Any | None = None,
        alias: str | None = None,
        alias_priority: int | None = _Unset,
        validation_alias: str | None = None,
        serialization_alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        gt: float | None = None,
        ge: float | None = None,
        lt: float | None = None,
        le: float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
        discriminator: str | None = None,
        strict: bool | None = _Unset,
        multiple_of: float | None = _Unset,
        allow_inf_nan: bool | None = _Unset,
        max_digits: int | None = _Unset,
        decimal_places: int | None = _Unset,
        examples: list[Any] | None = None,
        deprecated: deprecated | str | bool | None = None,
        include_in_schema: bool = True,
        json_schema_extra: dict[str, Any] | None = None,
    ):
        self.include_in_schema = include_in_schema
        kwargs = {
            "default": default,
            "default_factory": default_factory,
            "alias": alias,
            "title": title,
            "description": description,
            "gt": gt,
            "ge": ge,
            "lt": lt,
            "le": le,
            "min_length": min_length,
            "max_length": max_length,
            "discriminator": discriminator,
            "multiple_of": multiple_of,
            "allow_inf_nan": allow_inf_nan,
            "max_digits": max_digits,
            "decimal_places": decimal_places,
        }
        if examples is not None:
            kwargs["examples"] = examples
        current_json_schema_extra = json_schema_extra
        if PYDANTIC_VERSION_MINOR_TUPLE < (2, 7):
            self.deprecated = deprecated
        else:
            kwargs["deprecated"] = deprecated
        if PYDANTIC_V2:
            kwargs.update(
                {
                    "annotation": annotation,
                    "alias_priority": alias_priority,
                    "validation_alias": validation_alias,
                    "serialization_alias": serialization_alias,
                    "strict": strict,
                    "json_schema_extra": current_json_schema_extra,
                }
            )
            kwargs["pattern"] = pattern
        else:
            kwargs["regex"] = pattern
            kwargs.update(**current_json_schema_extra)  # type: ignore
        use_kwargs = {k: v for k, v in kwargs.items() if v is not _Unset}

        super().__init__(**use_kwargs)  # type: ignore

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.default})"


class Path(Param):  # type: ignore[misc]
    in_ = ParamTypes.path

    def __init__(  # noqa: PLR0913
        self,
        default: Any = ...,
        *,
        default_factory: Callable[[], Any] | None = _Unset,
        annotation: Any | None = None,
        alias: str | None = None,
        alias_priority: int | None = _Unset,
        validation_alias: str | None = None,
        serialization_alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        gt: float | None = None,
        ge: float | None = None,
        lt: float | None = None,
        le: float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
        discriminator: str | None = None,
        strict: bool | None = _Unset,
        multiple_of: float | None = _Unset,
        allow_inf_nan: bool | None = _Unset,
        max_digits: int | None = _Unset,
        decimal_places: int | None = _Unset,
        examples: list[Any] | None = None,
        deprecated: deprecated | str | bool | None = None,
        include_in_schema: bool = True,
        json_schema_extra: dict[str, Any] | None = None,
    ):
        assert default is ..., "Path parameters cannot have a default value"
        self.in_ = self.in_
        super().__init__(
            default=default,
            default_factory=default_factory,
            annotation=annotation,
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
            deprecated=deprecated,
            examples=examples,
            include_in_schema=include_in_schema,
            json_schema_extra=json_schema_extra,
        )


class Query(Param):  # type: ignore[misc]
    in_ = ParamTypes.query

    def __init__(  # noqa: PLR0913
        self,
        default: Any = Undefined,
        *,
        default_factory: Callable[[], Any] | None = _Unset,
        annotation: Any | None = None,
        alias: str | None = None,
        alias_priority: int | None = _Unset,
        validation_alias: str | None = None,
        serialization_alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        gt: float | None = None,
        ge: float | None = None,
        lt: float | None = None,
        le: float | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
        discriminator: str | None = None,
        strict: bool | None = _Unset,
        multiple_of: float | None = _Unset,
        allow_inf_nan: bool | None = _Unset,
        max_digits: int | None = _Unset,
        decimal_places: int | None = _Unset,
        examples: list[Any] | None = None,
        deprecated: deprecated | str | bool | None = None,
        include_in_schema: bool = True,
        json_schema_extra: dict[str, Any] | None = None,
    ):
        super().__init__(
            default=default,
            default_factory=default_factory,
            annotation=annotation,
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
            deprecated=deprecated,
            examples=examples,
            include_in_schema=include_in_schema,
            json_schema_extra=json_schema_extra,
        )
