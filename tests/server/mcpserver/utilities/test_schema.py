"""Tests for mcp.server.mcpserver.utilities.schema.dereference_local_refs."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.utilities.schema import dereference_local_refs


class TestDereferenceLocalRefs:
    def test_no_defs_returns_schema_unchanged(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        assert dereference_local_refs(schema) == schema

    def test_inlines_simple_ref(self) -> None:
        schema = {
            "type": "object",
            "properties": {"user": {"$ref": "#/$defs/User"}},
            "$defs": {"User": {"type": "object", "properties": {"name": {"type": "string"}}}},
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["user"] == {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        # $defs pruned when fully resolved
        assert "$defs" not in result

    def test_inlines_definitions_legacy_keyword(self) -> None:
        schema = {
            "properties": {"x": {"$ref": "#/definitions/Thing"}},
            "definitions": {"Thing": {"type": "integer"}},
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["x"] == {"type": "integer"}

    def test_dollar_defs_wins_when_both_present(self) -> None:
        schema = {
            "properties": {"x": {"$ref": "#/$defs/T"}},
            "$defs": {"T": {"type": "string"}},
            "definitions": {"T": {"type": "number"}},
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["x"] == {"type": "string"}

    def test_diamond_reference_resolved_once(self) -> None:
        schema = {
            "properties": {
                "a": {"$ref": "#/$defs/A"},
                "c": {"$ref": "#/$defs/C"},
            },
            "$defs": {
                "A": {"type": "object", "properties": {"d": {"$ref": "#/$defs/D"}}},
                "C": {"type": "object", "properties": {"d": {"$ref": "#/$defs/D"}}},
                "D": {"type": "string", "title": "the-d"},
            },
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["a"]["properties"]["d"] == {"type": "string", "title": "the-d"}
        assert result["properties"]["c"]["properties"]["d"] == {"type": "string", "title": "the-d"}
        assert "$defs" not in result

    def test_cycle_leaves_ref_in_place_and_preserves_def(self) -> None:
        # Node -> children[0] -> Node ... cyclic
        schema = {
            "type": "object",
            "properties": {"root": {"$ref": "#/$defs/Node"}},
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "next": {"$ref": "#/$defs/Node"},
                    },
                }
            },
        }
        result = dereference_local_refs(schema)
        # Cyclic ref left in place
        assert result["properties"]["root"]["properties"]["next"] == {"$ref": "#/$defs/Node"}
        # $defs entry for Node preserved so ref is resolvable
        assert "Node" in result["$defs"]

    def test_sibling_keywords_preserved_via_2020_12_semantics(self) -> None:
        schema = {
            "properties": {"x": {"$ref": "#/$defs/Base", "description": "override"}},
            "$defs": {
                "Base": {
                    "type": "string",
                    "description": "original",
                    "minLength": 1,
                }
            },
        }
        result = dereference_local_refs(schema)
        # Siblings override resolved, but other fields preserved
        assert result["properties"]["x"] == {
            "type": "string",
            "description": "override",
            "minLength": 1,
        }

    def test_external_ref_left_as_is(self) -> None:
        schema = {
            "properties": {"x": {"$ref": "https://example.com/schema.json"}},
            "$defs": {"Local": {"type": "string"}},
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["x"] == {"$ref": "https://example.com/schema.json"}

    def test_unknown_local_ref_left_as_is(self) -> None:
        schema = {
            "properties": {"x": {"$ref": "#/$defs/DoesNotExist"}},
            "$defs": {"Other": {"type": "string"}},
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["x"] == {"$ref": "#/$defs/DoesNotExist"}

    def test_nested_arrays_and_objects_are_traversed(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "list": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Item"},
                }
            },
            "$defs": {"Item": {"type": "integer"}},
        }
        result = dereference_local_refs(schema)
        assert result["properties"]["list"]["items"] == {"type": "integer"}

    def test_original_schema_not_mutated(self) -> None:
        schema = {
            "properties": {"x": {"$ref": "#/$defs/A"}},
            "$defs": {"A": {"type": "string"}},
        }
        original_defs = dict(schema["$defs"])
        _ = dereference_local_refs(schema)
        # Original still has $defs intact
        assert schema["$defs"] == original_defs
        assert schema["properties"]["x"] == {"$ref": "#/$defs/A"}

    def test_empty_defs_returns_schema_unchanged(self) -> None:
        """`$defs: {}` (empty container) is a no-op — returns input as-is."""
        schema = {"type": "object", "$defs": {}}
        result = dereference_local_refs(schema)
        assert result is schema  # same object — no copy made on the empty path

    def test_null_defs_returns_schema_unchanged(self) -> None:
        """`$defs: null` falls through the same empty-defs path."""
        schema: dict[str, Any] = {"type": "object", "$defs": None}
        result = dereference_local_refs(schema)
        assert result is schema

    def test_inlines_through_array_of_objects(self) -> None:
        """Refs nested inside arrays of dict items are recursed properly.

        Covers the `if isinstance(node, list)` branch of the inner inline().
        """
        schema = {
            "anyOf": [
                {"$ref": "#/$defs/A"},
                {"$ref": "#/$defs/B"},
            ],
            "$defs": {
                "A": {"type": "string"},
                "B": {"type": "integer"},
            },
        }
        result = dereference_local_refs(schema)
        assert result["anyOf"] == [{"type": "string"}, {"type": "integer"}]
