"""Keep `inspect.signature()` accurate for `defer_build` models before their first use.

The SDK's model bases set `defer_build=True`, so pydantic builds a model's core
schema, validator and serializer on first use instead of while the class
statement runs; a module full of models then costs almost nothing to import in
a process that never validates them.

The one observable pydantic ties to that build is the class's `__signature__`
(the synthesized `__init__` signature that `inspect.signature(Model)` reports):
under `defer_build` it exists only once the model has built, and until then a
class reports the generic `(**data)`. `DeferredSignature` is a class-level
`__signature__` that completes the (one-time) build via the public
`model_rebuild()` on first signature access, so runtime introspection matches an
eagerly-built model while nothing is built at import.
"""

from __future__ import annotations

from inspect import Signature
from typing import Any, TypeVar, cast

from pydantic import BaseModel

__all__ = ["DeferredSignature", "deferred_model", "install_deferred_signature", "new_deferred_signature"]

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class DeferredSignature:
    """Class-level `__signature__` for a `defer_build=True` pydantic model.

    First access completes the model build via `model_rebuild()` (public API,
    a no-op once complete); pydantic then binds its own signature on the class,
    replacing this attribute, and that is what gets returned. If the build cannot
    complete (an unresolvable forward reference), no signature results and
    `inspect` falls back to `__init__` exactly as for any unbuilt deferred model.
    """

    def __get__(self, obj: object | None, owner: type[BaseModel] | None = None) -> Any:
        if obj is not None or owner is None:
            # Instances take their signature from `__call__`; only the class has one.
            raise AttributeError("__signature__")
        # `raise_errors=False`: an annotation that cannot resolve yet leaves the
        # model unbuilt (and this attribute in place) instead of raising here,
        # so `inspect` falls back to `__init__` like it does for pydantic itself.
        owner.model_rebuild(raise_errors=False)
        bound = vars(owner).get("__signature__")
        if bound is None or bound is self:
            raise AttributeError("__signature__")
        return bound.__get__(None, owner) if hasattr(bound, "__get__") else bound


def new_deferred_signature() -> Signature:
    """A `DeferredSignature` typed as the `Signature` it stands in for.

    Assign it in a model class body WITHOUT an annotation (`__signature__ =
    new_deferred_signature()`), matching how `BaseModel` itself binds
    `__signature__`, so it never appears in `get_type_hints(Model)`.
    """
    return cast(Signature, DeferredSignature())


def install_deferred_signature(cls: type[BaseModel]) -> None:
    """Give a still-deferred model class its own lazily-completing `__signature__`.

    Meant for a base's `__pydantic_init_subclass__` hook: every deferred subclass
    needs its OWN `__signature__` entry, otherwise it would inherit an
    already-built parent's signature. A class that pydantic already completed
    (e.g. one that turned `defer_build` off) keeps the real signature it has.
    """
    if not cls.__pydantic_complete__:
        setattr(cls, "__signature__", new_deferred_signature())


def deferred_model(cls: type[_ModelT]) -> type[_ModelT]:
    """Class decorator for the root of a `defer_build` model hierarchy under `BaseModel`.

    Installs the lazy `__signature__` on `cls` and, via a `__pydantic_init_subclass__`
    hook, on every model that later subclasses it (a subclass inherits the deferred
    build through the config). Models deriving from the SDK bases (`MCPModel`,
    `WireModel`, `WireRootModel`) get this from the base and do not need it.
    """
    install_deferred_signature(cls)

    def __pydantic_init_subclass__(sub: type[BaseModel], **kwargs: Any) -> None:
        install_deferred_signature(sub)
        # Run whatever hook `cls`'s own bases define (BaseModel's is a no-op).
        # (`super()` from a classmethod defined outside the class body needs
        # both arguments; the two-argument form is opaque to the type checker.)
        cast(Any, super(cls, sub)).__pydantic_init_subclass__(**kwargs)

    setattr(cls, "__pydantic_init_subclass__", classmethod(__pydantic_init_subclass__))
    return cls
