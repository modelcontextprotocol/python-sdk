"""JSON Schema generator for tool schemas.

Centralizes the `GenerateJsonSchema` subclass used when rendering tool input and
output schemas. On top of turning pydantic's schema warnings into errors, it
enforces SEP-2106: a `$ref` that is not a same-document reference (a JSON Pointer
such as `#/$defs/Foo` or an `$anchor` such as `#Foo`) is an SSRF / fetch-DoS
vector and MUST NOT appear in a tool schema.

See: https://modelcontextprotocol.io/seps/2106-json-schema-2020-12#security-implications
"""

from __future__ import annotations

from typing import Any, cast

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue, JsonSchemaWarningKind
from pydantic_core import CoreSchema


class ExternalSchemaRefError(ValueError):
    """A tool schema contains a `$ref` that is not a same-document reference."""


class StrictJsonSchema(GenerateJsonSchema):
    """Render tool schemas, raising on pydantic warnings and external `$ref`s.

    Warnings (e.g. a non-serializable type) become errors so they surface at tool
    registration instead of silently producing a degenerate schema. External
    `$ref`s -- which pydantic never emits itself, but a user can inject via
    `Field(json_schema_extra=...)` -- are rejected for the same reason (SEP-2106).
    """

    def emit_warning(self, kind: JsonSchemaWarningKind, detail: str) -> None:
        raise ValueError(f"JSON schema warning: {kind} - {detail}")

    def generate(self, schema: CoreSchema, mode: Any = "validation") -> JsonSchemaValue:
        json_schema = super().generate(schema, mode)
        _reject_external_refs(json_schema)
        return json_schema


def _reject_external_refs(json_schema: JsonSchemaValue) -> None:
    external = sorted(_find_external_refs(json_schema))
    if external:
        raise ExternalSchemaRefError(
            f"Tool schema contains external $ref(s) that MUST NOT be dereferenced (SEP-2106): "
            f"{', '.join(external)}. Only same-document references (e.g. '#/$defs/Foo') are allowed."
        )


def _find_external_refs(node: Any) -> set[str]:
    external: set[str] = set()
    if isinstance(node, dict):
        mapping = cast("dict[str, Any]", node)
        ref = mapping.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            external.add(ref)
        for value in mapping.values():
            external |= _find_external_refs(value)
    elif isinstance(node, list):
        for item in cast("list[Any]", node):
            external |= _find_external_refs(item)
    return external
