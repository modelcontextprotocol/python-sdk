"""Tests for ``dereference_json_schema``."""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest
from pydantic import BaseModel

from mcp.server.mcpserver.utilities.json_schema import dereference_json_schema

# ---- flat schemas (no $defs) ----


def test_returns_schema_unchanged_when_no_defs() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    result = dereference_json_schema(schema)
    assert result == schema


def test_strips_empty_defs_block() -> None:
    """A `$defs: {}` block adds noise without referents — strip it."""
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "$defs": {},
    }
    result = dereference_json_schema(schema)
    assert "$defs" not in result
    assert result["properties"]["x"] == {"type": "integer"}


def test_does_not_mutate_input() -> None:
    schema = {
        "$defs": {"X": {"type": "string"}},
        "properties": {"x": {"$ref": "#/$defs/X"}},
    }
    snapshot = copy.deepcopy(schema)
    dereference_json_schema(schema)
    assert schema == snapshot


# ---- single-level inlining ----


def test_inlines_single_top_level_ref() -> None:
    schema = {
        "type": "object",
        "properties": {"addr": {"$ref": "#/$defs/Address"}},
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            }
        },
    }
    result = dereference_json_schema(schema)
    assert "$defs" not in result
    assert result["properties"]["addr"] == {
        "type": "object",
        "properties": {"city": {"type": "string"}},
    }


def test_inlines_multiple_refs_to_same_def() -> None:
    """Re-used definitions inline at every use site."""
    schema = {
        "type": "object",
        "properties": {
            "home": {"$ref": "#/$defs/Address"},
            "work": {"$ref": "#/$defs/Address"},
        },
        "$defs": {"Address": {"type": "object", "properties": {"city": {"type": "string"}}}},
    }
    result = dereference_json_schema(schema)
    assert "$defs" not in result
    assert result["properties"]["home"] == result["properties"]["work"]
    assert result["properties"]["home"]["properties"]["city"] == {"type": "string"}


def test_inlines_inside_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {
            "addresses": {
                "type": "array",
                "items": {"$ref": "#/$defs/Address"},
            }
        },
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            }
        },
    }
    result = dereference_json_schema(schema)
    assert "$defs" not in result
    assert result["properties"]["addresses"]["items"]["properties"]["city"] == {
        "type": "string"
    }


def test_inlines_inside_anyof() -> None:
    schema = {
        "properties": {
            "value": {
                "anyOf": [{"$ref": "#/$defs/Address"}, {"type": "null"}],
            }
        },
        "$defs": {"Address": {"type": "object"}},
    }
    result = dereference_json_schema(schema)
    assert result["properties"]["value"]["anyOf"][0] == {"type": "object"}


# ---- transitive expansion ----


def test_inlines_transitively() -> None:
    """A def whose body contains a ref to another def should resolve both."""
    schema = {
        "properties": {"p": {"$ref": "#/$defs/Person"}},
        "$defs": {
            "Person": {
                "type": "object",
                "properties": {"home": {"$ref": "#/$defs/Address"}},
            },
            "Address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        },
    }
    result = dereference_json_schema(schema)
    assert "$defs" not in result
    home = result["properties"]["p"]["properties"]["home"]
    assert home == {"type": "object", "properties": {"city": {"type": "string"}}}


# ---- siblings to $ref ----


def test_merges_sibling_keys_into_resolved_ref() -> None:
    """JSON Schema 2020-12 allows ``$ref`` alongside annotation keys.
    Pydantic emits this pattern; the sibling keys should override the
    resolved body so the user-facing annotations are preserved."""
    schema = {
        "properties": {
            "addr": {
                "$ref": "#/$defs/Address",
                "title": "Home address",
                "description": "Where the user lives",
            }
        },
        "$defs": {
            "Address": {
                "type": "object",
                "title": "Generic Address",  # this should be overridden
                "properties": {"city": {"type": "string"}},
            }
        },
    }
    result = dereference_json_schema(schema)
    addr = result["properties"]["addr"]
    assert addr["title"] == "Home address"
    assert addr["description"] == "Where the user lives"
    assert addr["properties"]["city"] == {"type": "string"}


# ---- external & unknown refs ----


def test_preserves_external_refs() -> None:
    """External URLs are not internal `#/$defs/` references — leave them alone."""
    schema = {
        "properties": {"x": {"$ref": "https://example.com/schemas/X.json"}},
        "$defs": {"Y": {"type": "string"}},
    }
    result = dereference_json_schema(schema)
    assert result["properties"]["x"] == {"$ref": "https://example.com/schemas/X.json"}


def test_preserves_unknown_internal_refs() -> None:
    """A `#/$defs/X` pointing at a missing def should be preserved verbatim;
    failing silently would hide a real bug in the producer."""
    schema = {
        "properties": {"x": {"$ref": "#/$defs/Nonexistent"}},
        "$defs": {"Other": {"type": "string"}},
    }
    result = dereference_json_schema(schema)
    assert result["properties"]["x"] == {"$ref": "#/$defs/Nonexistent"}


def test_preserves_non_defs_internal_refs() -> None:
    """`#/properties/foo` (a path into the root schema) isn't a `$defs`
    pointer; we don't try to resolve it."""
    schema = {
        "properties": {
            "x": {"type": "integer"},
            "y": {"$ref": "#/properties/x"},
        },
        "$defs": {"X": {"type": "string"}},
    }
    result = dereference_json_schema(schema)
    assert result["properties"]["y"] == {"$ref": "#/properties/x"}


# ---- cycles ----


def test_direct_self_reference_preserved_at_boundary() -> None:
    """A model containing itself can't be fully inlined; the cycle
    must be preserved or the function would infinite-loop. We keep
    the ``$ref`` at the boundary and retain the entry in ``$defs``."""
    schema = {
        "properties": {"root": {"$ref": "#/$defs/Tree"}},
        "$defs": {
            "Tree": {
                "type": "object",
                "properties": {
                    "value": {"type": "integer"},
                    "children": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/Tree"},
                    },
                },
            }
        },
    }
    result = dereference_json_schema(schema)
    # The top-level use should be inlined (we walk through Tree once).
    root = result["properties"]["root"]
    assert root["type"] == "object"
    # The inner self-ref is preserved at the boundary.
    inner = root["properties"]["children"]["items"]
    assert inner == {"$ref": "#/$defs/Tree"}
    # $defs is retained because there's still a live ref into it.
    assert "Tree" in result["$defs"]


def test_mutual_recursion_preserved() -> None:
    """A refers to B, B refers to A — neither can be fully inlined."""
    schema = {
        "properties": {"a": {"$ref": "#/$defs/A"}},
        "$defs": {
            "A": {
                "type": "object",
                "properties": {"b": {"$ref": "#/$defs/B"}},
            },
            "B": {
                "type": "object",
                "properties": {"a": {"$ref": "#/$defs/A"}},
            },
        },
    }
    result = dereference_json_schema(schema)
    # Top-level A is expanded once.
    a_outer = result["properties"]["a"]
    assert a_outer["type"] == "object"
    # B inside is also expanded once.
    b_inner = a_outer["properties"]["b"]
    assert b_inner["type"] == "object"
    # The A inside B is the cycle boundary — preserved as $ref.
    a_inner = b_inner["properties"]["a"]
    assert a_inner == {"$ref": "#/$defs/A"}
    assert "A" in result["$defs"]


# ---- real Pydantic models ----


def test_real_pydantic_nested_model_is_inlined() -> None:
    """End-to-end: a Pydantic model with a nested BaseModel emits $defs +
    $ref, and our function inlines them so the result has no $defs and
    the nested field is a full schema object."""

    class Address(BaseModel):
        street: str
        city: str

    class Person(BaseModel):
        name: str
        home: Address

    raw = Person.model_json_schema()
    # Sanity check: Pydantic does emit $defs/$ref for this shape.
    assert "$defs" in raw
    assert raw["properties"]["home"] == {"$ref": "#/$defs/Address"}

    flat = dereference_json_schema(raw)
    assert "$defs" not in flat
    home = flat["properties"]["home"]
    assert home["type"] == "object"
    assert home["properties"]["street"] == {"title": "Street", "type": "string"}
    assert home["properties"]["city"] == {"title": "City", "type": "string"}


def test_real_pydantic_list_of_nested_model() -> None:
    """List of nested model — verify items are inlined."""

    class Item(BaseModel):
        sku: str

    class Cart(BaseModel):
        items: list[Item]

    flat = dereference_json_schema(Cart.model_json_schema())
    assert "$defs" not in flat
    items_schema = flat["properties"]["items"]
    assert items_schema["type"] == "array"
    inlined = items_schema["items"]
    assert inlined["type"] == "object"
    assert inlined["properties"]["sku"] == {"title": "Sku", "type": "string"}


def test_real_pydantic_self_referencing_model_kept_as_cycle() -> None:
    """A Pydantic model that lists itself recursively should produce a
    schema where the self-reference is preserved (otherwise we'd hang)."""

    class Node(BaseModel):
        value: int
        children: list[Node] = []

    Node.model_rebuild()
    flat = dereference_json_schema(Node.model_json_schema())
    # The self-reference inside the children items survives.
    assert _contains_ref(flat["properties"]["children"], "#/$defs/Node")
    assert "Node" in flat.get("$defs", {})


def _contains_ref(node: Any, target: str) -> bool:
    """Walk ``node`` and return True if any ``$ref`` equals ``target``."""
    if isinstance(node, dict):
        node_dict = cast("dict[str, Any]", node)
        if node_dict.get("$ref") == target:
            return True
        return any(_contains_ref(v, target) for v in node_dict.values())
    if isinstance(node, list):
        node_list = cast("list[Any]", node)
        return any(_contains_ref(item, target) for item in node_list)
    return False


# ---- regression / safety properties ----


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object"},
        {"type": "array", "items": {"type": "integer"}},
        {"oneOf": [{"type": "integer"}, {"type": "string"}]},
    ],
)
def test_idempotent_on_flat_schemas(schema: dict[str, Any]) -> None:
    """Applying the function twice should not change a flat schema."""
    once = dereference_json_schema(schema)
    twice = dereference_json_schema(once)
    assert once == twice == schema


def test_idempotent_after_full_inline() -> None:
    """Re-applying after a full inline should be a no-op (no $defs left)."""
    schema = {
        "properties": {"addr": {"$ref": "#/$defs/A"}},
        "$defs": {"A": {"type": "object"}},
    }
    once = dereference_json_schema(schema)
    twice = dereference_json_schema(once)
    assert once == twice
