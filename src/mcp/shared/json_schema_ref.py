"""External `$ref` detection for JSON Schemas (SEP-2106).

SEP-2106 permits the full JSON Schema 2020-12 vocabulary in tool schemas,
including `$ref`. A `$ref` resolving to a network URI is an SSRF / fetch-DoS
vector: implementations MUST NOT automatically dereference `$ref` values that
are not same-document references (a JSON Pointer such as `#/$defs/Foo` or an
`$anchor` such as `#Foo`).

See: https://modelcontextprotocol.io/seps/2106-json-schema-2020-12#security-implications
"""

from __future__ import annotations

from typing import Any, cast


class ExternalSchemaRefError(ValueError):
    """A JSON Schema contains a `$ref` that is not a same-document reference."""


def is_same_document_ref(ref: str) -> bool:
    """Whether `ref` is a same-document reference (`#`, `#/...` pointer, or `#anchor`)."""
    return ref.startswith("#")


def find_external_refs(schema: Any) -> list[str]:
    """Collect every `$ref` in `schema` that is not a same-document reference."""
    external: list[str] = []
    _walk(schema, external)
    return external


def reject_external_refs(schema: Any, *, context: str) -> None:
    """Raise `ExternalSchemaRefError` if `schema` contains a non-same-document `$ref`.

    Args:
        schema: The JSON Schema (or fragment) to inspect.
        context: Human-readable label for the schema, used in the error message.

    Raises:
        ExternalSchemaRefError: If any `$ref` is not a same-document reference.
    """
    external = find_external_refs(schema)
    if external:
        raise ExternalSchemaRefError(
            f"{context} contains external $ref(s) that MUST NOT be dereferenced (SEP-2106): "
            f"{', '.join(external)}. Only same-document references (e.g. '#/$defs/Foo') are allowed."
        )


def _walk(node: Any, external: list[str]) -> None:
    if isinstance(node, dict):
        mapping = cast("dict[str, Any]", node)
        ref = mapping.get("$ref")
        if isinstance(ref, str) and not is_same_document_ref(ref):
            external.append(ref)
        for value in mapping.values():
            _walk(value, external)
    elif isinstance(node, list):
        for item in cast("list[Any]", node):
            _walk(item, external)
