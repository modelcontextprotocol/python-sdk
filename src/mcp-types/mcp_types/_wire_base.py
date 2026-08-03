"""Shared pydantic bases for the type layer.

`DeferredModel` makes pydantic build a model's validator on first use instead
of at import (`defer_build`) and serialises those first-use builds across
threads; `DeferredAdapter` does the same for the module-level union
`TypeAdapter`s. The generated `mcp_types._v*` wire packages use `WireModel`
for object models and `WireRootModel` for their root/union models: every
class in a package must defer together, since an eagerly-built union
inline-generates the schema of each deferred member it references.
"""

import inspect
import threading
from collections.abc import Mapping
from dataclasses import is_dataclass
from typing import Annotated, Any, Generic, Literal, TypeVar, get_args, get_origin

from pydantic import BaseModel, ConfigDict, RootModel, TypeAdapter
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode
from typing_extensions import is_typeddict

RootT = TypeVar("RootT")
AdaptedT = TypeVar("AdaptedT")

# Released pydantic (<= 2.13) does not lock a deferred model's or adapter's
# first-use build, so first use from several threads at once can raise
# (pydantic/pydantic#13419). One process-wide lock serialises those first
# builds; it is re-entrant because a build rebuilds referenced models on the
# same thread. Nothing is rebuilt once built, so the lock is only ever
# contended during first use.
_REBUILD_LOCK = threading.RLock()


class DeferredModel(BaseModel):
    """`BaseModel` built on first use, with that first build serialised across threads."""

    model_config = ConfigDict(defer_build=True)

    @classmethod
    def model_rebuild(
        cls,
        *,
        force: bool = False,
        raise_errors: bool = True,
        _parent_namespace_depth: int = 2,
        _types_namespace: Mapping[str, Any] | None = None,
    ) -> bool | None:
        with _REBUILD_LOCK:  # +1: this override adds one frame above pydantic's namespace lookup
            return super().model_rebuild(
                force=force,
                raise_errors=raise_errors,
                _parent_namespace_depth=_parent_namespace_depth + 1,
                _types_namespace=_types_namespace,
            )

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        # Generation reads the core schemas of referenced models that another thread
        # may be first-building at that moment, so it runs under the same lock (without
        # it, concurrent first calls were observed returning ancestor schemas). This
        # serialises every call, since pydantic regenerates the schema each time, which
        # is acceptable: no request path generates protocol-model JSON schemas.
        with _REBUILD_LOCK:
            return super().model_json_schema(
                by_alias=by_alias,
                ref_template=ref_template,
                schema_generator=schema_generator,
                mode=mode,
                union_format=union_format,
            )


# `DeferredModel` and `DeferredAdapter` override pydantic's build and schema entry points
# with pydantic's own signatures mirrored parameter-for-parameter, so type checkers and
# `inspect.signature` still see the real methods. If a future pydantic adds a parameter to
# one of them these overrides need updating; the signature-parity test in
# tests/types/test_wire_base.py is the tripwire. Pydantic decorates `TypeAdapter` with
# `@final`, but overriding `rebuild()` is the only hook for serialising a deferred adapter's
# first-use build (there is no lock in released pydantic); the subclass is behaviourally an
# ordinary TypeAdapter.
class DeferredAdapter(TypeAdapter[AdaptedT], Generic[AdaptedT]):  # pyright: ignore[reportGeneralTypeIssues]
    """`TypeAdapter` built on first use, with that first build serialised on the same lock.

    An adapter over a union of deferred models builds outside any model's own
    `model_rebuild`, so its build is serialised here instead. Targets that carry
    their own config (a BaseModel, dataclass or TypedDict, possibly wrapped in
    `Annotated`) keep it; every other target gets `defer_build=True`.
    """

    def __init__(
        self, type: Any, *, config: ConfigDict | None = None, _parent_depth: int = 2, module: str | None = None
    ) -> None:
        # pydantic rejects an adapter `config` for a target that carries its own (a
        # BaseModel, dataclass or TypedDict, possibly wrapped in Annotated) - the same
        # rule pydantic applies; a model target already defers via its own config, and
        # every other target defers its build here.
        target = get_args(type)[0] if get_origin(type) is Annotated else type
        carries_config = inspect.isclass(target) and (
            issubclass(target, BaseModel) or is_dataclass(target) or is_typeddict(target)
        )
        if config is None and not carries_config:
            config = ConfigDict(defer_build=True)
        super().__init__(type, config=config, _parent_depth=_parent_depth + 1, module=module)  # +1: this frame

    def rebuild(
        self,
        *,
        force: bool = False,
        raise_errors: bool = True,
        _parent_namespace_depth: int = 2,
        _types_namespace: Mapping[str, Any] | None = None,
    ) -> bool | None:
        with _REBUILD_LOCK:  # +1: this override adds one frame above pydantic's namespace lookup
            return super().rebuild(
                force=force,
                raise_errors=raise_errors,
                _parent_namespace_depth=_parent_namespace_depth + 1,
                _types_namespace=_types_namespace,
            )


class WireModel(DeferredModel):
    """Base for generated wire models: enables `populate_by_name`; subclasses set `extra` themselves."""

    model_config = ConfigDict(populate_by_name=True)


class WireRootModel(DeferredModel, RootModel[RootT], Generic[RootT]):
    """Base for the generated root (union/alias) models: a deferred `RootModel`."""
