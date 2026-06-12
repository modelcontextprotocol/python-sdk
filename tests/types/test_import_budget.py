"""Pin the lazy-loading behavior of the per-version model packages.

The wire boundary (``mcp.types.wire``) validates payloads through the
committed per-version model packages (``mcp.types.v2024_11_05`` ...
``mcp.types.v2026_07_28``), each of which defines on the order of a hundred
pydantic models. Building those classes is the dominant cost of loading the
packages, so the boundary imports a version package only on first use and
``mcp.types.__init__`` does not import the boundary module at all: programs
that never touch the wire boundary never pay for it.

These tests run a fresh interpreter per case because the test process has
already imported ``mcp`` (a subprocess is the only way to observe a clean
``sys.modules``).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from mcp.types import wire

# Matches exactly the per-version model packages (mcp.types.v2024_11_05,
# ..., mcp.types.v2026_07_28) and no other mcp.types submodule.
_LAZY_MODULE_PATTERN = r"^mcp\.types\.v\d{4}_\d{2}_\d{2}$"

_REPORT_LAZY_MODULES = """\
import json
import re
import sys

{import_statement}

pattern = re.compile({pattern!r})
loaded = sorted(
    name for name in sys.modules if name == "mcp.types.wire" or pattern.match(name)
)
print(json.dumps(loaded))
"""


@pytest.mark.parametrize("import_statement", ["import mcp", "import mcp.types"])
def test_version_packages_and_wire_module_are_not_imported_eagerly(import_statement: str) -> None:
    """No version package (and not the boundary module) loads as an import side effect."""
    script = _REPORT_LAZY_MODULES.format(import_statement=import_statement, pattern=_LAZY_MODULE_PATTERN)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_version_package_names_match_the_lazy_module_pattern() -> None:
    """The pattern the subprocess checks really names the version packages.

    Guards the subprocess assertion against going vacuous if the packages
    are ever renamed: every module the boundary loads lazily must match the
    pattern, so a rename shows up here instead of silently passing above.
    """
    for module_name in wire._VERSION_MODULES.values():
        assert re.match(_LAZY_MODULE_PATTERN, module_name), module_name
