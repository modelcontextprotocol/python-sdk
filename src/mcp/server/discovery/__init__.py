"""Progressive disclosure tool discovery system for MCP servers.

This module provides the infrastructure for optional progressive disclosure
of tools through semantic grouping and on-demand loading.

Recommended approach: Define tool groups directly in Python using ToolGroup
with standard MCP Tool objects. No filesystem dependencies needed.
"""

from mcp.server.discovery.manager import ToolGroupManager
from mcp.server.discovery.tool_group import ToolGroup

__all__ = [
    "ToolGroupManager",
    "ToolGroup",
]
