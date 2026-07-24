"""Shared pydantic bases for the generated `mcp_types.v*` packages and the monolith."""

from typing import Any, ClassVar, Final, get_args

from pydantic import BaseModel, ConfigDict, SerializationInfo, SerializerFunctionWrapHandler, model_serializer

_UNSET: Final[object] = object()
"""Tells a field explicitly set to `None` apart from one that was never set."""


class WireModel(BaseModel):
    """Base for generated wire models: enables `populate_by_name`; subclasses set `extra` themselves."""

    model_config = ConfigDict(populate_by_name=True)


class KeepRequiredNullable(BaseModel):
    """Base for models carrying a required nullable field, e.g. `Task.ttl` (`number | null`).

    Every dump path passes `exclude_none=True` to omit unset optionals, but that cannot tell an
    unset optional from a required field whose value is legitimately null, so it drops both and
    leaves a body that fails the schema it was just validated against. This puts the required
    ones back, and only those: a field the caller filtered out with `include`/`exclude`, or one
    that was never set at all, stays absent.

    Mixed in only where it is needed, since a wrap serializer costs per dump:
    `scripts/gen_surface_types.py` derives the surface classes from the schema and the monolith
    counterparts take it by hand, with `tests/types/test_parity.py` checking the set is complete.
    """

    _nullable_required_fields: ClassVar[tuple[tuple[str, str], ...] | None] = None
    """`(attribute, wire alias)` per required nullable field; resolved on first dump, then cached."""

    @classmethod
    def _resolve_nullable_required(cls) -> tuple[tuple[str, str], ...]:
        """Find the fields `exclude_none` must not drop, once per concrete class.

        Deferred to first use rather than `__pydantic_init_subclass__`: the generated modules
        use `from __future__ import annotations` and finish with `model_rebuild()`, so a forward
        reference is still a string at class-creation time and would resolve to nothing. Each
        class resolves its own set, since subclasses add fields (`GetTaskResult` is `Result`
        plus `Task`).
        """
        resolved = tuple(
            (name, field.serialization_alias or field.alias or name)
            for name, field in cls.model_fields.items()
            if field.is_required() and _admits_none(field.annotation)
        )
        cls._nullable_required_fields = resolved
        return resolved

    @model_serializer(mode="wrap")
    def _keep_required_nullable(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo):
        # The return is deliberately unannotated: pydantic builds the serialization JSON schema
        # from this signature, and any annotation collapses the whole model's schema to an
        # opaque object for anyone generating schemas over these types.
        data = handler(self)
        if not info.exclude_none:
            return data
        # `__dict__`, not attribute lookup: a subclass must resolve its own set rather than
        # inherit whichever ancestor happened to be dumped first.
        cls = type(self)
        fields = cls.__dict__.get("_nullable_required_fields")
        if fields is None:
            fields = cls._resolve_nullable_required()
        for name, alias in fields:
            if self.__dict__.get(name, _UNSET) is not None:
                continue
            if (info.include is not None and name not in info.include) or (
                info.exclude is not None and name in info.exclude
            ):
                continue  # the caller filtered this field out; exclude_none is not why it is gone
            data.setdefault(alias if info.by_alias else name, None)
        return data


def _admits_none(annotation: Any) -> bool:
    """Whether a field's annotation accepts `None`, including a bare `Any`."""
    if annotation is Any or annotation is None:
        return True
    return type(None) in get_args(annotation)
