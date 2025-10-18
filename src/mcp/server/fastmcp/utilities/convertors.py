from __future__ import annotations

import math
import uuid
from typing import Any, ClassVar, Generic, TypeVar, get_args

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

T = TypeVar("T")


class Convertor(Generic[T]):
    regex: ClassVar[str] = ""
    python_type: Any = Any  # type hint for runtime type

    def __init_subclass__(cls, **kwargs: dict[str, Any]) -> None:
        super().__init_subclass__(**kwargs)
        # Extract the concrete type from the generic base
        base = cls.__orig_bases__[0]  # type: ignore[attr-defined]
        args = get_args(base)
        if args:
            cls.python_type = args[0]  # type: ignore[assignment]
        else:
            raise RuntimeError(f"Bad converter definition in class {cls.__name__}")

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: GetCoreSchemaHandler):
        return core_schema.any_schema()

    def convert(self, value: str) -> T:
        raise NotImplementedError()

    def to_string(self, value: T) -> str:
        raise NotImplementedError()


class StringConvertor(Convertor[str]):
    regex = r"[^/]+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        value = str(value)
        assert "/" not in value, "May not contain path separators"
        assert value, "Must not be empty"
        return value


class PathConvertor(Convertor[str]):
    regex = r".*"

    def convert(self, value: str) -> str:
        return str(value)

    def to_string(self, value: str) -> str:
        return str(value)


class IntegerConvertor(Convertor[int]):
    regex = r"[0-9]+"

    def convert(self, value: str) -> int:
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Value '{value}' is not a valid integer")

    def to_string(self, value: int) -> str:
        value = int(value)
        assert value >= 0, "Negative integers are not supported"
        return str(value)


class FloatConvertor(Convertor[float]):
    regex = r"[0-9]+(?:\.[0-9]+)?"

    def convert(self, value: str) -> float:
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Value '{value}' is not a valid float")

    def to_string(self, value: float) -> str:
        value = float(value)
        assert value >= 0.0, "Negative floats are not supported"
        assert not math.isnan(value), "NaN values are not supported"
        assert not math.isinf(value), "Infinite values are not supported"
        return f"{value:.20f}".rstrip("0").rstrip(".")


class UUIDConvertor(Convertor[uuid.UUID]):
    regex = r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"

    def convert(self, value: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except ValueError:
            raise ValueError(f"Value '{value}' is not a valid UUID")

    def to_string(self, value: uuid.UUID) -> str:
        return str(value)


CONVERTOR_TYPES: dict[str, Convertor[Any]] = {
    "str": StringConvertor(),
    "path": PathConvertor(),
    "int": IntegerConvertor(),
    "float": FloatConvertor(),
    "uuid": UUIDConvertor(),
}
