"""`docs/advanced/import-cost.md`: the prewarm recipe does what the page says."""

import json
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The recipe's effect is only observable in a fresh interpreter: this process has long
# since loaded the wire packages and built the models.
PROBE = """
import json, sys
import mcp_types

before = {
    "wire_2025_loaded": "mcp_types._v2025_11_25" in sys.modules,
    "tool_built": mcp_types.Tool.__pydantic_complete__,
}
import docs_src.import_cost.tutorial001  # the recipe under test
after = {
    "wire_2025_loaded": "mcp_types._v2025_11_25" in sys.modules,
    "tool_built": mcp_types.Tool.__pydantic_complete__,
}
print(json.dumps({"before": before, "after": after}))
"""


def test_prewarm_recipe_loads_the_wire_package_and_builds_the_models() -> None:
    """tutorial001: before the recipe nothing is loaded/built; after `mcp.warm(version)` the
    named version's wire package is imported and the models are built."""
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=REPO_ROOT,  # the recipe module is imported by its docs_src path
        # pydantic plugins (e.g. logfire) building models is the environment's cost, not ours
        env={**os.environ, "PYDANTIC_DISABLE_PLUGINS": "__all__"},
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed["before"] == {"wire_2025_loaded": False, "tool_built": False}
    assert observed["after"] == {"wire_2025_loaded": True, "tool_built": True}
