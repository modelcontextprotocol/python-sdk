"""
Example demonstrating recommended layout for larger FastMCP servers.

This example shows how to organize tools into separate modules
and implement versioned tools using name-based versioning.
"""

from .server import mcp

__all__ = ["mcp"]
