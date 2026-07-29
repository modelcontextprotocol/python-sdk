"""`mcp.shared._lazy_submodules`: package attribute access imports the submodule of that name."""

import subprocess
import sys
from types import ModuleType

import pytest
from inline_snapshot import snapshot

import tests.shared.lazy_submodule_fixture as fixture_pkg


def test_package_attribute_imports_the_submodule_of_that_name():
    """SDK-defined: `pkg.<name>` imports `pkg.<name>` on first touch and binds it on the package."""
    submodule = getattr(fixture_pkg, "fine")
    assert isinstance(submodule, ModuleType)
    assert submodule.MARKER == "ok"
    assert submodule is sys.modules["tests.shared.lazy_submodule_fixture.fine"]
    assert vars(fixture_pkg)["fine"] is submodule


def test_missing_submodule_raises_attribute_error():
    """SDK-defined: a name with no such submodule is a plain AttributeError."""
    with pytest.raises(AttributeError):
        getattr(fixture_pkg, "no_such_submodule")


def test_dunder_probe_raises_attribute_error_without_a_submodule_search():
    """SDK-defined: dunder names are protocol probes, never submodules."""
    with pytest.raises(AttributeError):
        getattr(fixture_pkg, "__no_such_dunder__")


def test_submodule_with_a_missing_dependency_surfaces_the_real_import_error():
    """SDK-defined: an existing submodule that fails to import raises its own error, not AttributeError."""
    with pytest.raises(ModuleNotFoundError) as exc_info:
        getattr(fixture_pkg, "broken")
    assert exc_info.value.name == "definitely_not_installed_dependency_xyz"


def test_bare_import_mcp_still_resolves_deep_submodule_chains():
    """SDK-defined: after only `import mcp`, `mcp.client.stdio.stdio_client` etc. still resolve.

    A fresh interpreter is required: this process already imported those modules.
    """
    probe = (
        "import mcp\n"
        "print([mcp.client.stdio.stdio_client.__name__, mcp.server.stdio.stdio_server.__name__,\n"
        "       mcp.shared.memory.__name__, mcp.os.posix.__name__])\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == snapshot("['stdio_client', 'stdio_server', 'mcp.shared.memory', 'mcp.os.posix']\n")
