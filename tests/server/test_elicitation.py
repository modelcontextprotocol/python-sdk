"""`mcp.server.elicitation` module-level behaviour."""

import mcp_types._v2025_11_25 as wire

from mcp.server import elicitation


def test_wire_schema_gate_type_is_still_reachable_on_the_module():
    """`PrimitiveSchemaDefinition` used to be bound here by a module-level import; it now
    resolves lazily to the same class, and `dir()` still lists it."""
    assert elicitation.PrimitiveSchemaDefinition is wire.PrimitiveSchemaDefinition
    assert "PrimitiveSchemaDefinition" in dir(elicitation)
