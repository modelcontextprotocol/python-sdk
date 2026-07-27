"""The `mcp.server.fastmcp` import path is a deprecated alias for `mcp.server.mcpserver`."""

import importlib
import sys
from types import ModuleType

import pytest

from mcp import MCPDeprecationWarning
from mcp.server.mcpserver import Audio, Context, Icon, Image, MCPServer


def _import_fastmcp_fresh() -> ModuleType:
    # The warning fires on module execution, so drop any cached module first.
    sys.modules.pop("mcp.server.fastmcp", None)
    return importlib.import_module("mcp.server.fastmcp")


def test_importing_fastmcp_warns_and_names_the_replacement():
    with pytest.warns(MCPDeprecationWarning, match="renamed to MCPServer"):
        _import_fastmcp_fresh()


def test_fastmcp_reexports_the_v1_surface_as_the_v2_objects():
    with pytest.warns(MCPDeprecationWarning):
        fastmcp = _import_fastmcp_fresh()

    assert fastmcp.__all__ == ["FastMCP", "Context", "Image", "Audio", "Icon"]
    assert fastmcp.FastMCP is MCPServer
    assert fastmcp.Context is Context
    assert fastmcp.Image is Image
    assert fastmcp.Audio is Audio
    assert fastmcp.Icon is Icon
