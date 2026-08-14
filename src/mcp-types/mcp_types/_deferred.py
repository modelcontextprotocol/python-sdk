"""Support for the SDK's `defer_build=True` pydantic models.

The SDK's model bases set `defer_build=True`, so pydantic builds a model's core
schema, validator and serializer on first use instead of while the class
statement runs; a module full of models then costs almost nothing to import in
a process that never validates them. Two things need help until that first
build happens:

* `inspect.signature(Model)`. Under `defer_build` the synthesized `__init__`
  signature (`__signature__`) exists only once the model has built; until then
  a class would report the generic `(**data)`. `DeferredSignature` is a
  class-level `__signature__` that completes the (one-time) build via the
  public `model_rebuild()` on first signature access, so runtime introspection
  matches an eagerly-built model while nothing is built at import.
* The first build under concurrency. Released pydantic (<= 2.13) does not
  lock `model_rebuild()`, so several threads first-using one model at once
  (sync tools on worker threads, one session per thread) can raise
  `AttributeError: __pydantic_core_schema__` or install a stale validator
  (pydantic#13419; fixed unreleased in pydantic#13438). One process-wide
  reentrant lock around the build closes that window: a late thread waits,
  then finds the model complete and its own rebuild is a no-op.

`deferred_model` installs both on the root class of a deferred model hierarchy
(the type-layer bases `MCPModel` / `WireModel` / `WireRootModel`, the JSON-RPC
envelopes, and the `mcp` package's own model roots); subclasses inherit them.

This is a private module of `mcp-types`, but the `mcp` package (which
exact-pins its `mcp-types` sibling) imports `deferred_model` for its own model
roots too: keep the signatures stable across both packages.
"""

from __future__ import annotations

import threading
from inspect import Signature
from typing import Any, Final, TypeVar, cast

from pydantic import BaseModel

__all__ = [
    "REBUILD_LOCK",
    "DeferredSignature",
    "deferred_model",
    "install_deferred_signature",
    "new_deferred_signature",
]

_ModelT = TypeVar("_ModelT", bound=BaseModel)

REBUILD_LOCK: Final = threading.RLock()
"""Serializes the first (deferred) build of every SDK model across threads.

Reentrant on purpose: completing one model rebuilds the models it references
on the same thread, re-entering `model_rebuild()`. Held only while a model
actually builds (and while a not-yet-built model's JSON schema is generated,
a cold path); a completed model's `model_rebuild()` returns before the lock,
and no per-message path takes it.

The lock is held across pydantic's own build machinery, and that machinery
runs user code: custom `__get_pydantic_core_schema__` hooks and subclass /
metaclass hooks execute under it. So the usual lock-order rule applies - user
code must not block on some other lock inside those hooks while another
thread holds that lock and first-uses a model - and a thread mid-build during
`os.fork()` leaves the child's lock held (the standard fork-with-threads
caveat). Both are the same terms upstream pydantic adopted for its own,
identical, process-wide rebuild lock (pydantic#13438); once a pydantic release
containing it is our dependency floor this SDK lock can go. A host that calls
`mcp.warm()` at startup builds everything on one thread and never contends here.
"""


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

    Bound in a class namespace WITHOUT an annotation (matching how `BaseModel`
    itself binds `__signature__`), so it never appears in `get_type_hints(Model)`.
    """
    return cast(Signature, DeferredSignature())


def install_deferred_signature(cls: type[BaseModel]) -> None:
    """Give a still-deferred model class its own lazily-completing `__signature__`.

    Every deferred subclass needs its OWN `__signature__` entry, otherwise it
    would inherit an already-built parent's signature. A class that pydantic
    already completed (e.g. one that turned `defer_build` off) keeps the real
    signature it has.
    """
    if not cls.__pydantic_complete__:
        setattr(cls, "__signature__", new_deferred_signature())


def deferred_model(cls: type[_ModelT]) -> type[_ModelT]:
    """Class decorator for the root of a `defer_build=True` model hierarchy.

    Installs, on `cls` and (through inheritance) on every model that later
    subclasses it - a subclass inherits the deferred build through the config:

    * the lazy `__signature__`, via a `__pydantic_init_subclass__` hook that
      stamps a fresh one on each still-deferred subclass;
    * a `model_rebuild` classmethod that takes `REBUILD_LOCK`, so the first
      build of any model in the hierarchy is serialized across threads (public
      pydantic API; `_parent_namespace_depth + 1` accounts for this extra
      frame);
    * a `model_json_schema` classmethod that completes the (deferred) model
      and generates the schema under that lock, so concurrent first schema
      calls race neither on the not-yet-built class nor on a referenced
      (e.g. mutually recursive) model that another thread is completing.

    Raises:
        TypeError: `cls` does not set `defer_build=True` in its `model_config`,
            or defines its own `__pydantic_init_subclass__` (which the hook
            installed here would silently replace).
    """
    if not cls.model_config.get("defer_build"):
        raise TypeError(f"@deferred_model expects {cls.__name__} to set model_config['defer_build'] = True")
    if "__pydantic_init_subclass__" in vars(cls):
        raise TypeError(f"@deferred_model would replace {cls.__name__}'s own __pydantic_init_subclass__")

    install_deferred_signature(cls)

    def __pydantic_init_subclass__(sub: type[BaseModel], **kwargs: Any) -> None:
        install_deferred_signature(sub)
        # Chain to whatever hook `cls`'s bases define (BaseModel's is a no-op).
        # (`super()` from a classmethod defined outside the class body needs the
        # two-argument form, which is opaque to the type checker.)
        cast(Any, super(cls, sub)).__pydantic_init_subclass__(**kwargs)

    def model_rebuild(sub: type[BaseModel], *args: Any, _parent_namespace_depth: int = 2, **kwargs: Any) -> Any:
        # An already-built model is the common case: answer it like pydantic
        # does, without touching the lock.
        if sub.__pydantic_complete__ and not (args or kwargs.get("force")):
            return None
        # One process-wide lock serializes the deferred first build across
        # threads; a late thread finds the model complete and no-ops.
        with REBUILD_LOCK:
            return cast(Any, super(cls, sub)).model_rebuild(
                *args, _parent_namespace_depth=_parent_namespace_depth + 1, **kwargs
            )

    def model_json_schema(sub: type[BaseModel], *args: Any, **kwargs: Any) -> Any:
        # Complete the class AND generate under the lock: pydantic re-reads a
        # class's (mock) core schema around a concurrent first build, and the
        # generation for one model reads the core schema of every model it
        # references (a mutually recursive family such as the wire JSON models
        # references its siblings) while another thread may still be
        # completing one of those. Schema generation is a cold path, so it
        # simply serializes with the deferred first builds.
        with REBUILD_LOCK:
            if not sub.__pydantic_complete__:
                sub.model_rebuild(raise_errors=False)
            return cast(Any, super(cls, sub)).model_json_schema(*args, **kwargs)

    setattr(cls, "__pydantic_init_subclass__", classmethod(__pydantic_init_subclass__))
    setattr(cls, "model_rebuild", classmethod(model_rebuild))
    setattr(cls, "model_json_schema", classmethod(model_json_schema))
    return cls
