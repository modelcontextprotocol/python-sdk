"""`mcp.server.elicitation` module-level behaviour."""

import builtins
from collections.abc import Mapping, Sequence
from types import ModuleType
from unittest.mock import patch

import mcp_types._v2025_11_25 as wire
from pydantic import BaseModel

from mcp.server import elicitation
from mcp.server.elicitation import render_elicitation_schema


def test_wire_schema_gate_type_is_still_reachable_on_the_module():
    """`PrimitiveSchemaDefinition` used to be bound here by a module-level import; it now
    resolves lazily to the same class, and `dir()` still lists it."""
    assert elicitation.PrimitiveSchemaDefinition is wire.PrimitiveSchemaDefinition
    assert "PrimitiveSchemaDefinition" in dir(elicitation)


def test_rendering_schemas_repeatedly_executes_no_further_imports():
    """The wire-schema gate type is resolved once; rendering more schemas afterwards never
    runs another import statement (the import cost is a one-time first-use bill, not a
    per-call one)."""

    class Prompt(BaseModel):
        name: str
        age: int = 0

    render_elicitation_schema(Prompt)  # warm-up: pays the one-time wire-package import

    real_import = builtins.__import__
    import_calls: list[str] = []

    def counting_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        import_calls.append(name)
        return real_import(name, globals, locals, fromlist, level)

    with patch.object(builtins, "__import__", counting_import):
        for _ in range(20):
            render_elicitation_schema(Prompt)

    # pydantic runs its own function-level imports while generating a schema; the SDK's
    # gate (the wire package) must not add any of ours.
    assert [name for name in import_calls if name.startswith("mcp")] == []
