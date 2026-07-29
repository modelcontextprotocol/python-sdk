"""Deferred (`defer_build`) models keep runtime introspection identical to eagerly-built ones."""

import inspect
import typing

import pytest
from mcp_types import Implementation, Tool
from mcp_types._deferred import deferred_model
from mcp_types._types import MCPModel
from pydantic import BaseModel, ConfigDict


def test_never_used_model_reports_its_real_init_signature() -> None:
    """`inspect.signature()` completes the deferred build itself, so a model nobody has
    validated yet still reports its fields rather than pydantic's generic `(**data)`."""

    class Probe(MCPModel):
        first_name: str
        age: int = 0

    assert not Probe.__pydantic_complete__
    signature = inspect.signature(Probe)
    assert Probe.__pydantic_complete__  # the first signature access built it, once
    assert str(signature) == "(*, firstName: str, age: int = 0) -> None"


def test_deferred_signature_is_not_a_type_hint_and_is_class_only() -> None:
    """The lazy `__signature__` never leaks into `get_type_hints`, and instances do not
    expose one (matching `BaseModel`)."""

    class Probe(MCPModel):
        name: str

    assert "__signature__" not in typing.get_type_hints(Probe)
    assert not hasattr(Probe.model_construct(name="x"), "__signature__")  # still-deferred class
    assert not hasattr(Implementation(name="probe", version="1"), "__signature__")
    assert "__signature__" not in typing.get_type_hints(Tool)


def test_a_subclass_that_disables_defer_build_keeps_its_eager_signature() -> None:
    """A subclass may turn `defer_build` back off; it builds at class creation and keeps the
    signature pydantic gave it (the lazy one is only installed on still-deferred classes)."""

    class Eager(MCPModel):
        model_config = ConfigDict(defer_build=False)
        value: int

    assert Eager.__pydantic_complete__
    assert str(inspect.signature(Eager)) == "(*, value: int) -> None"


def test_decorated_root_model_covers_its_subclasses_too() -> None:
    """`@deferred_model` gives a `BaseModel`-derived deferred model - and every model that
    later subclasses it - an accurate pre-first-use signature."""

    @deferred_model
    class Root(BaseModel):
        model_config = ConfigDict(defer_build=True)
        x: int

    class Child(Root):
        y: str = "y"

    for cls, expected in ((Root, "(*, x: int) -> None"), (Child, "(*, x: int, y: str = 'y') -> None")):
        assert not cls.__pydantic_complete__
        assert str(inspect.signature(cls)) == expected


def test_unresolvable_model_falls_back_to_the_generic_signature() -> None:
    """A model whose build cannot complete (a forward reference that does not resolve at
    that point) reports the generic initializer signature, as pydantic does for any
    unbuilt model - and asking for the signature never raises."""

    class Pending(MCPModel):
        value: "Later"

    # `Later` is not defined yet, so the deferred build cannot complete here.
    assert str(inspect.signature(Pending)) == "(**data: 'Any') -> 'None'"
    assert not Pending.__pydantic_complete__
    with pytest.raises(NameError):
        Pending.model_rebuild()

    class Later(MCPModel):  # defined only afterwards: too late for `Pending`
        done: bool

    assert Later
