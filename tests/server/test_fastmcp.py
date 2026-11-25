"""The removed v1 import path `mcp.server.fastmcp` fails with a pointer to the migration guide."""

import importlib
import sys

import pytest
from inline_snapshot import snapshot

import mcp.server
from mcp.server.mcpserver import MCPServer


def test_importing_fastmcp_raises_module_not_found_that_points_at_the_migration_guide() -> None:
    """SDK-defined: the v1 path fails with the same exception type and `.name` as a module
    that genuinely does not exist, but the message names the replacement and the guide."""
    with pytest.raises(ModuleNotFoundError) as exc_info:
        importlib.import_module("mcp.server.fastmcp")

    assert exc_info.value.name == "mcp.server.fastmcp"
    assert str(exc_info.value) == snapshot(
        "No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer "
        "(from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at "
        "https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver "
        "or pin 'mcp<2' to keep running v1 code."
    )
    # A module that raises while executing is never cached, so nothing is left behind.
    assert "mcp.server.fastmcp" not in sys.modules
    assert not hasattr(mcp.server, "fastmcp")


def test_importing_a_fastmcp_submodule_raises_the_parent_pointer() -> None:
    """SDK-defined: a deep v1 path executes `mcp.server.fastmcp` first, so it fails with that
    module's message and `.name` rather than a bare error for the leaf."""
    with pytest.raises(ModuleNotFoundError) as parent:
        importlib.import_module("mcp.server.fastmcp")
    with pytest.raises(ModuleNotFoundError) as exc_info:
        importlib.import_module("mcp.server.fastmcp.utilities.types")

    assert exc_info.value.name == "mcp.server.fastmcp"
    assert str(exc_info.value) == str(parent.value)


def test_v1_first_import_shim_falls_back_to_mcpserver() -> None:
    """SDK-defined: projects that support both majors try the v1 import and fall back on
    `ModuleNotFoundError` (the narrowest guard seen in the wild), which is why the pointer is
    raised as exactly that type and not as a bare `ImportError` or after a warning."""
    fell_back = False
    try:
        server_class: type = importlib.import_module("mcp.server.fastmcp").FastMCP
    except ModuleNotFoundError:
        fell_back = True
        server_class = MCPServer

    assert fell_back
    assert server_class is MCPServer
