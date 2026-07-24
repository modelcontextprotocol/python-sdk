"""Shared pydantic bases for the generated `mcp_types.v*` packages and the monolith."""

from functools import cache
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, SerializationInfo, SerializerFunctionWrapHandler, model_serializer


class WireModel(BaseModel):
    """Base for generated wire models: enables `populate_by_name`; subclasses set `extra` themselves."""

    model_config = ConfigDict(populate_by_name=True)


def admits_none(annotation: Any) -> bool:
    """Whether a field's annotation accepts `None`, including a bare `Any`."""
    return annotation is Any or annotation is None or type(None) in get_args(annotation)


@cache
def _nullable_required_fields(model: type[BaseModel]) -> tuple[tuple[str, str], ...]:
    """The `(attribute, wire alias)` pairs `exclude_none` must not drop from `model`.

    Resolved on first dump rather than at class creation: the generated modules use
    `from __future__ import annotations` and finish with `model_rebuild()`, so a forward
    reference is still a string while the class body runs and would resolve to nothing.
    Keyed on the concrete class, since subclasses add fields (`GetTaskResult` is `Result`
    plus `Task`).
    """
    return tuple(
        (name, field.serialization_alias or field.alias or name)
        for name, field in model.model_fields.items()
        if field.is_required() and admits_none(field.annotation)
    )


class KeepRequiredNullable(BaseModel):
    """Base for models carrying a required nullable field, e.g. `Task.ttl` (`number | null`).

    Every dump path passes `exclude_none=True` to omit unset optionals, but that cannot tell an
    unset optional from a required field whose value is legitimately null, so it drops both and
    leaves a body that fails the schema it was just validated against. This puts the required
    ones back, and only those: a field the caller filtered out with `include`/`exclude` stays
    absent, because there `exclude_none` is not why it went.

    Mixed in only where it is needed, since a wrap serializer costs per dump and pydantic walks
    one per model in the tree: `scripts/gen_surface_types.py` derives the surface classes from
    the schema and the monolith counterparts take it by hand, with `tests/types/test_parity.py`
    checking the resulting set against every built model.
    """

    @model_serializer(mode="wrap")
    def _keep_required_nullable(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo):
        # The return is deliberately unannotated: pydantic builds the serialization JSON schema
        # from this signature, and any annotation collapses the whole model's schema to an
        # opaque object for anyone generating schemas over these types.
        data = handler(self)
        if not info.exclude_none:
            return data
        # `serialize_by_alias` is the config-level spelling of the `by_alias` argument; reading
        # only the argument would restore the one key under a spelling the rest of the dump did
        # not use.
        by_alias = info.by_alias or type(self).model_config.get("serialize_by_alias", False)
        for name, alias in _nullable_required_fields(type(self)):
            if getattr(self, name, None) is not None:
                continue
            if (info.include is not None and name not in info.include) or (
                info.exclude is not None and name in info.exclude
            ):
                continue
            data.setdefault(alias if by_alias else name, None)
        return data
