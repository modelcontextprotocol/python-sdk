"""The `mcp` package namespace: lazy exports (PEP 562) that stay identical to the eager originals."""

import subprocess
import sys

import pytest
from inline_snapshot import snapshot

import mcp
import mcp.shared.exceptions


def test_exported_name_is_the_home_module_object_and_is_cached_on_the_package():
    """SDK-defined: `mcp.MCPError` is `mcp.shared.exceptions.MCPError`, cached after first access."""
    assert mcp.MCPError is mcp.shared.exceptions.MCPError
    assert vars(mcp)["MCPError"] is mcp.shared.exceptions.MCPError


def test_dir_lists_every_export_and_the_bound_submodules():
    """SDK-defined: `dir(mcp)` reports all of `__all__` plus the submodules a bare import binds."""
    listing = set(dir(mcp))
    assert set(mcp.__all__) <= listing
    assert {"client", "os", "server", "shared", "types"} <= listing


def test_unknown_attribute_raises_attribute_error():
    """SDK-defined: a name that is neither an export nor a submodule raises AttributeError."""
    with pytest.raises(AttributeError):
        getattr(mcp, "no_such_name")


def test_bare_import_mcp_does_not_load_the_types_or_client_or_server_stacks():
    """SDK-defined: `import mcp` is lazy - the protocol types and the client/server stacks
    load on first use, not on package import.

    A fresh interpreter is required to observe `sys.modules` after a bare import: this
    test process imported all of them long ago.
    """
    probe = (
        "import mcp, sys\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in {'mcp', 'mcp_types', 'pydantic'}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == snapshot("['mcp']\n")
