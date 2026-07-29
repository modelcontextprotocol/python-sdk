"""`mcp.shared._lazy`: lazy exports and submodules resolved on attribute access."""

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


def test_lazy_export_is_loaded_once_and_cached_in_the_namespace():
    """SDK-defined: a lazy export runs its loader on first access, then reads as a plain attribute."""
    assert fixture_pkg.ANSWER == 42
    assert fixture_pkg.ANSWER == 42
    assert fixture_pkg.load_calls == 1
    assert vars(fixture_pkg)["ANSWER"] == 42


def test_dir_lists_exports_and_submodules_but_not_the_lazy_machinery():
    """SDK-defined: `dir(pkg)` reports the lazy exports and real submodules, and hides the
    helper's own bindings so the namespace looks the way an eager module would."""
    listing = dir(fixture_pkg)
    assert {"ANSWER", "fine", "broken", "load_calls"} <= set(listing)
    assert {"__getattr__", "__dir__", "_lazy_module_attrs"}.isdisjoint(listing)


def test_missing_name_raises_attribute_error_without_importing_anything():
    """SDK-defined: a name that is neither an export nor a real submodule is a plain
    AttributeError; nothing is speculatively imported for it."""
    with pytest.raises(AttributeError):
        getattr(fixture_pkg, "no_such_submodule")
    assert "tests.shared.lazy_submodule_fixture.no_such_submodule" not in sys.modules


def test_dunder_probe_raises_attribute_error_without_a_submodule_search():
    """SDK-defined: dunder names are protocol probes, never lazy names."""
    with pytest.raises(AttributeError):
        getattr(fixture_pkg, "__no_such_dunder__")


def test_submodule_with_a_missing_dependency_surfaces_the_real_import_error():
    """SDK-defined: an existing submodule that fails to import raises its own error, not AttributeError."""
    with pytest.raises(ModuleNotFoundError) as exc_info:
        getattr(fixture_pkg, "broken")
    assert exc_info.value.name == "definitely_not_installed_dependency_xyz"


def test_bare_import_mcp_still_resolves_deep_submodule_chains():
    """SDK-defined: after only `import mcp`, `mcp.client.stdio.stdio_client` etc. still resolve,
    and each package's `dir()` lists submodules that were never imported explicitly.

    A fresh interpreter is required: this process already imported those modules.
    """
    probe = (
        "import mcp\n"
        "print([mcp.client.stdio.stdio_client.__name__, mcp.server.stdio.stdio_server.__name__,\n"
        "       mcp.shared.memory.__name__, mcp.os.posix.utilities.__name__,\n"
        "       mcp.os.win32.utilities.__name__, mcp.server.auth.handlers.token.__name__,\n"
        "       mcp.server.auth.middleware.auth_context.__name__,\n"
        "       'stdio' in dir(mcp.client), 'stdio' in dir(mcp.server), 'exceptions' in dir(mcp.shared)])\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == snapshot("""\
['stdio_client', 'stdio_server', 'mcp.shared.memory', 'mcp.os.posix.utilities', 'mcp.os.win32.utilities', \
'mcp.server.auth.handlers.token', 'mcp.server.auth.middleware.auth_context', True, True, True]
""")
