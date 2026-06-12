"""Import-time budget: the types package loads its wire boundary lazily.

`import mcp` (and `import mcp.types`) must not load the wire boundary module
or the per-version fact blocks; they load on first access of
`mcp.types.wire`. Asserted in a subprocess so the check sees a fresh
interpreter, not whatever this test session already imported.
"""

import json
import subprocess
import sys

import pytest

import mcp.types

_PROBE = """\
import json
import sys

import mcp
import mcp.types

lazy = ["mcp.types.wire", "mcp.types._version_facts", "mcp.types._shaping"]
loaded_too_early = [name for name in lazy if name in sys.modules]

wire = mcp.types.wire  # first attribute access loads the boundary
print(
    json.dumps(
        {
            "loaded_too_early": loaded_too_early,
            "loads_on_access": wire.KNOWN_PROTOCOL_VERSIONS[0] == "2024-11-05",
        }
    )
)
"""


def test_importing_mcp_does_not_load_the_wire_boundary() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    result = json.loads(completed.stdout)
    assert result["loaded_too_early"] == []
    assert result["loads_on_access"] is True


def test_unknown_types_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no attribute 'does_not_exist'"):
        getattr(mcp.types, "does_not_exist")
