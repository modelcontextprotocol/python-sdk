"""The `mcp` package namespace: lazy exports (PEP 562) that stay identical to the eager originals.

The import-footprint half of the contract (what `import mcp` may load) lives in
tests/test_import_guards.py, together with the other entry points' guards.
"""

import pytest

import mcp
import mcp.server.session
import mcp.server.stdio
import mcp.shared.exceptions
from mcp.client.session_group import ClientSessionGroup


def test_exported_name_is_the_home_module_object_and_is_cached_on_the_package():
    """SDK-defined: `mcp.MCPError` is `mcp.shared.exceptions.MCPError`, cached after first access."""
    assert mcp.MCPError is mcp.shared.exceptions.MCPError
    assert vars(mcp)["MCPError"] is mcp.shared.exceptions.MCPError


def test_client_and_server_reexports_are_the_defining_objects():
    """SDK-defined: `mcp.ServerSession`, `mcp.stdio_server` and `mcp.ClientSessionGroup`
    resolve on first access to the very objects their defining modules export."""
    assert mcp.ServerSession is mcp.server.session.ServerSession
    assert mcp.stdio_server is mcp.server.stdio.stdio_server
    assert mcp.ClientSessionGroup is ClientSessionGroup


def test_dir_lists_every_export_and_the_bound_submodules():
    """SDK-defined: `dir(mcp)` reports all of `__all__` plus the submodules a bare import binds."""
    listing = set(dir(mcp))
    assert set(mcp.__all__) <= listing
    assert {"client", "os", "server", "shared", "types"} <= listing


def test_unknown_attribute_raises_attribute_error():
    """SDK-defined: a name that is neither an export nor a submodule raises AttributeError."""
    with pytest.raises(AttributeError):
        getattr(mcp, "no_such_name")
