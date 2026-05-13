"""JSON Schema post-processing utilities.

Pydantic's :meth:`pydantic.BaseModel.model_json_schema` emits a ``$defs``
block with named definitions for nested models, and ``$ref`` pointers
at each use site. The output is fully valid JSON Schema, but some MCP
clients don't resolve internal references when discovering tools via
``tools/list``. For those clients, fields whose types are nested models
become unusable.

This module provides :func:`dereference_json_schema`, an opt-in helper
that inlines ``$defs`` references into the schema body. It's safe to
apply at any point in the schema lifecycle (the function does not
mutate its input) and conservative about edge cases — external
references and self-referential definitions are preserved unchanged.
"""

from __future__ import annotations

import copy
from typing import Any, cast

_INTERNAL_DEFS_PREFIX = "#/$defs/"


def dereference_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with internal ``$defs`` references inlined.

    Replaces each ``{"$ref": "#/$defs/<name>"}`` node with the body of
    the corresponding ``$defs`` entry, recursing into nested objects
    and arrays. Self-referential definitions (a model whose schema
    contains a ``$ref`` back to itself, directly or transitively) are
    preserved as ``$ref`` at the cycle boundary; the ``$defs`` entries
    they depend on are retained so the output schema remains valid.

    Only internal ``#/$defs/`` references are resolved. External
    references (URLs, pointers into other documents) are preserved
    verbatim. Sibling keys alongside a ``$ref`` (allowed in JSON Schema
    2020-12 and emitted by Pydantic for some types) are merged into
    the resolved object, with sibling values taking precedence.

    Args:
        schema: A JSON Schema dict. Not mutated.

    Returns:
        A new schema dict with internal refs inlined. The top-level
        ``$defs`` block is removed when fully dereferenced, and
        retained (containing only the cycle definitions) otherwise.

    Example::

        from pydantic import BaseModel
        from mcp.server.mcpserver.utilities.json_schema import (
            dereference_json_schema,
        )

        class Address(BaseModel):
            street: str
            city: str

        class Person(BaseModel):
            name: str
            home: Address

        flat = dereference_json_schema(Person.model_json_schema())
        # flat["properties"]["home"] is now the full Address schema
        # rather than {"$ref": "#/$defs/Address"}.
    """
    schema = copy.deepcopy(schema)
    defs: dict[str, Any] = schema.pop("$defs", {}) or {}
    if not defs:
        return schema

    cycle_roots: set[str] = set()

    def _expand(node: Any, resolving: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            node_dict = cast("dict[str, Any]", node)
            ref = node_dict.get("$ref")
            if isinstance(ref, str) and ref.startswith(_INTERNAL_DEFS_PREFIX):
                name = ref[len(_INTERNAL_DEFS_PREFIX) :]
                if name not in defs:
                    # Unknown ref — preserve verbatim so the schema stays
                    # honest about what wasn't resolved.
                    return node_dict
                if name in resolving:
                    # Cycle: leave the $ref in place at the boundary and
                    # remember to keep the corresponding definition in
                    # the output's $defs.
                    cycle_roots.add(name)
                    return node_dict
                resolved = _expand(defs[name], (*resolving, name))
                siblings: dict[str, Any] = {
                    k: v for k, v in node_dict.items() if k != "$ref"
                }
                if not siblings:
                    return resolved
                if isinstance(resolved, dict):
                    resolved_dict = cast("dict[str, Any]", resolved)
                    merged: dict[str, Any] = dict(resolved_dict)
                    for k, v in siblings.items():
                        merged[k] = _expand(v, resolving)
                    return merged
                # $ref pointed at a non-dict (shouldn't happen with
                # well-formed schemas, but stay defensive).
                return node_dict
            expanded_children: dict[str, Any] = {
                k: _expand(v, resolving) for k, v in node_dict.items()
            }
            return expanded_children
        if isinstance(node, list):
            node_list = cast("list[Any]", node)
            return [_expand(item, resolving) for item in node_list]
        return node

    expanded = _expand(schema, ())
    assert isinstance(expanded, dict)
    result: dict[str, Any] = cast("dict[str, Any]", expanded)

    if cycle_roots:
        # Re-expand each cycle root with itself in the resolving set so
        # the inner $ref stays at the boundary while other nested refs
        # in the definition body are inlined.
        result["$defs"] = {
            name: _expand(defs[name], (name,)) for name in cycle_roots
        }

    return result
