"""JSON Schema utilities for tool input schema preparation.

LLM clients consuming `tools/list` often cannot resolve JSON Schema ``$ref``
pointers and serialize referenced parameters as stringified JSON instead of
structured objects. This module provides :func:`dereference_local_refs` which
inlines local ``$ref`` pointers so emitted tool schemas are self-contained.

This matches the behavior of the typescript-sdk (see
`modelcontextprotocol/typescript-sdk#1563`_) and go-sdk.

.. _modelcontextprotocol/typescript-sdk#1563:
   https://github.com/modelcontextprotocol/typescript-sdk/pull/1563
"""

from __future__ import annotations

from typing import TypeAlias, cast

JSONPrimitive: TypeAlias = None | str | int | float | bool
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]


def dereference_local_refs(schema: JSONObject) -> JSONObject:
    """Inline local ``$ref`` pointers in a JSON Schema.

    Behavior mirrors ``dereferenceLocalRefs`` in the TypeScript SDK:

    - Caches resolved defs so diamond references (A→B→D, A→C→D) only resolve D once.
    - Cycles are detected and left in place — cyclic ``$ref`` pointers are kept
      along with their ``$defs`` entries so existing recursive schemas continue
      to work (degraded). Non-cyclic refs in the same schema are still inlined.
    - Sibling keywords alongside ``$ref`` are preserved per JSON Schema 2020-12
      (e.g. ``{"$ref": "#/$defs/X", "description": "override"}``).
    - Non-local ``$ref`` (external URLs, fragments outside ``$defs``) are left as-is.
    - Root self-references (``$ref: "#"``) are not handled — no library produces them.

    If the schema has no ``$defs`` (or ``definitions``) container, it is returned
    unchanged.

    Args:
        schema: The JSON Schema to process. Not mutated.

    Returns:
        A new schema dict with local refs inlined. The ``$defs`` container is
        pruned to only the cyclic entries that remain referenced.
    """
    # ``$defs`` is the standard keyword since JSON Schema 2019-09.
    # ``definitions`` is the legacy equivalent from drafts 04–07.
    # If both exist (malformed), ``$defs`` takes precedence.
    if "$defs" in schema:
        defs_key = "$defs"
    elif "definitions" in schema:
        defs_key = "definitions"
    else:
        return schema

    raw_defs = schema[defs_key]
    if raw_defs is None:
        return schema
    if not isinstance(raw_defs, dict):
        return schema

    defs: JSONObject = raw_defs
    if not defs:
        return schema

    # Cache resolved defs to avoid redundant traversal on diamond references.
    resolved_defs: dict[str, JSONValue] = {}
    # Def names where a cycle was detected — their $ref is left in place and
    # their $defs entries must be preserved in the output.
    cyclic_defs: set[str] = set()
    prefix = f"#/{defs_key}/"

    def inline(node: JSONValue, stack: set[str]) -> JSONValue:
        if node is None or isinstance(node, str | int | float | bool):
            return node
        if isinstance(node, list):
            return [inline(item, stack) for item in node]
        if not isinstance(node, dict):  # pragma: no cover
            # Defensive: valid JSON only contains None/str/int/float/bool/list/dict.
            # Reachable only if a non-JSON-shaped value sneaks into a schema.
            return node

        ref = node.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith(prefix):
                # External or non-local ref — leave as-is.
                return node
            def_name = ref[len(prefix) :]
            if def_name not in defs:
                # Unknown def — leave the ref untouched (pydantic shouldn't produce these).
                return node
            if def_name in stack:
                # Cycle detected — leave $ref in place, mark def for preservation.
                cyclic_defs.add(def_name)
                return node

            if def_name in resolved_defs:
                resolved = resolved_defs[def_name]
            else:
                stack.add(def_name)
                resolved = inline(defs[def_name], stack)
                stack.discard(def_name)
                resolved_defs[def_name] = resolved

            # Siblings of $ref (JSON Schema 2020-12).
            siblings: JSONObject = {k: v for k, v in node.items() if k != "$ref"}
            if siblings and isinstance(resolved, dict):
                resolved_schema = cast(JSONObject, resolved)
                resolved_siblings: JSONObject = {key: inline(value, stack) for key, value in siblings.items()}
                return {**resolved_schema, **resolved_siblings}
            return resolved

        # Regular object — recurse into values, but skip the top-level $defs container.
        result: JSONObject = {}
        for key, value in node.items():
            if node is schema and key in ("$defs", "definitions"):
                continue
            result[key] = inline(value, stack)
        return result

    inlined = inline(schema, set())
    if not isinstance(inlined, dict):
        # Shouldn't happen — a schema object always produces an object.
        return schema  # pragma: no cover

    # Preserve only cyclic defs in the output.
    if cyclic_defs:
        preserved: JSONObject = {name: defs[name] for name in cyclic_defs if name in defs}
        inlined[defs_key] = preserved

    return inlined
