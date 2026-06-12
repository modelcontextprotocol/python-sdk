"""The wire boundary stays off the package import path.

Importing `mcp` (or `mcp.types`) must not load `mcp.types.wire` or any
per-version model module; the boundary is imported on first use only.
Asserted in a subprocess so the check observes a cold interpreter.
"""

import subprocess
import sys

_PROBE = """\
import sys

import mcp
import mcp.types

loaded = sorted(
    name for name in sys.modules if name == "mcp.types.wire" or name.startswith("mcp.types.v20")
)
if loaded:
    print(",".join(loaded))
    raise SystemExit(1)
"""


def test_importing_mcp_does_not_load_the_wire_boundary() -> None:
    """No version-keyed module may be paid for by users who never touch the
    wire boundary."""
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, f"version-keyed modules loaded at import time: {completed.stdout!r}"
