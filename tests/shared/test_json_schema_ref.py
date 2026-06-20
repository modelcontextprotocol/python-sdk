from __future__ import annotations

import pytest

from mcp.shared.json_schema_ref import (
    ExternalSchemaRefError,
    find_external_refs,
    is_same_document_ref,
    reject_external_refs,
)


@pytest.mark.parametrize(
    "ref",
    [
        "#",
        "#/$defs/Foo",
        "#/properties/bar",
        "#Foo",
    ],
)
def test_same_document_refs_allowed(ref: str):
    assert is_same_document_ref(ref) is True
    schema = {"type": "object", "properties": {"x": {"$ref": ref}}}
    assert find_external_refs(schema) == []
    reject_external_refs(schema, context="schema")


@pytest.mark.parametrize(
    "ref",
    [
        "https://example.com/schema.json",
        "http://localhost:9999/canary.json",
        "https://example.com/schema.json#/$defs/Foo",
        "urn:example:schema",
        "file:///etc/passwd",
        "schema.json",
        "./local.json",
        "//example.com/schema.json",
    ],
)
def test_external_refs_detected(ref: str):
    assert is_same_document_ref(ref) is False
    schema = {"type": "object", "properties": {"x": {"$ref": ref}}}
    assert find_external_refs(schema) == [ref]


def test_reject_external_refs_raises_with_context():
    schema = {"properties": {"x": {"$ref": "https://evil.example/s.json"}}}
    with pytest.raises(ExternalSchemaRefError) as exc_info:
        reject_external_refs(schema, context="Output schema for tool 'lookup'")
    message = str(exc_info.value)
    assert "Output schema for tool 'lookup'" in message
    assert "https://evil.example/s.json" in message


def test_find_external_refs_nested_in_lists_and_composition():
    schema = {
        "type": "object",
        "allOf": [
            {"properties": {"a": {"$ref": "#/$defs/A"}}},
            {"properties": {"b": {"$ref": "https://example.com/b.json"}}},
        ],
        "items": [{"$ref": "https://example.com/c.json"}],
        "$defs": {"A": {"type": "string"}},
    }
    assert sorted(find_external_refs(schema)) == [
        "https://example.com/b.json",
        "https://example.com/c.json",
    ]


def test_non_string_ref_is_ignored():
    schema = {"$ref": {"not": "a string"}, "properties": {"x": {"$ref": 123}}}
    assert find_external_refs(schema) == []


def test_scalar_and_empty_inputs():
    assert find_external_refs(None) == []
    assert find_external_refs("just a string") == []
    assert find_external_refs(42) == []
    assert find_external_refs({}) == []
    assert find_external_refs([]) == []
