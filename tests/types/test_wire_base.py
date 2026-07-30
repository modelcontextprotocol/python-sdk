"""The generated wire packages' bases keep import cheap: pydantic builds each model on first use."""

import mcp_types._v2025_11_25 as v2025
import mcp_types._v2026_07_28 as v2026
from mcp_types._wire_base import WireModel, WireRootModel
from pydantic import BaseModel


def test_wire_model_defers_the_pydantic_build_to_first_use() -> None:
    """SDK-defined: a `WireModel` subclass creates its class without building a validator;
    the first `model_validate` builds it, once."""

    class Probe(WireModel):
        x: int

    assert not Probe.__pydantic_complete__  # class creation built no validator
    assert Probe.model_validate({"x": 1}).x == 1  # first use builds it, once
    assert Probe.__pydantic_complete__


def test_wire_root_model_defers_the_parameterized_base_and_the_alias() -> None:
    """SDK-defined: a `WireRootModel[T]` alias defers both itself and its generic
    parameterization, and still validates through the root on first use."""

    class Payload(WireModel):
        x: int

    class Alias(WireRootModel[Payload]):
        root: Payload

    assert not Alias.__pydantic_complete__
    assert not WireRootModel[Payload].__pydantic_complete__  # the parameterization is a class too
    assert Alias.model_validate({"x": 2}).root.x == 2


def test_every_generated_class_derives_from_a_deferred_base() -> None:
    """An eagerly-built union rollup would regenerate every deferred model's schema inline."""
    for module in (v2025, v2026):
        models = [c for c in vars(module).values() if isinstance(c, type) and issubclass(c, BaseModel)]
        assert models
        for cls in models:
            assert issubclass(cls, WireModel | WireRootModel), f"{module.__name__}.{cls.__name__}"


def test_generated_classes_have_complete_field_metadata_at_import() -> None:
    """Dependency-ordered emission resolves every annotation at class creation.

    Only the genuinely recursive JSON alias trio may still name a class defined
    later (its own cycle); every other class must expose complete `model_fields`
    (aliases included) without a first-use build.
    """
    recursion = {"JSONArray", "JSONObject", "JSONValue"}
    for module in (v2025, v2026):
        for name, cls in vars(module).items():
            if isinstance(cls, type) and issubclass(cls, WireModel) and name not in recursion:
                assert cls.__pydantic_fields_complete__, f"{module.__name__}.{name}"
    assert v2026.CallToolRequestParams.model_fields["meta"].alias == "_meta"
