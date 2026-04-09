from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.logging import get_logger

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context

logger = get_logger(__name__)


class ToolManager:
    """Manages MCPServer tools."""

    def __init__(
        self,
        warn_on_duplicate_tools: bool = True,
        *,
        tools: list[Tool] | None = None,
    ):
        self._tools: dict[str, Tool] = {}
        self.warn_on_duplicate_tools = warn_on_duplicate_tools
        if tools is not None:
            for tool in tools:
                self.add_tool(tool)

    def get_tool(self, name: str) -> Tool | None:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def add_tool(
        self,
        tool: Tool,
    ) -> Tool:
        """Add a tool to the manager."""
        existing = self._tools.get(tool.name)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.name}")
            return existing
        self._tools[tool.name] = tool
        return tool

    def remove_tool(self, name: str) -> None:
        """Remove a tool by name."""
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        del self._tools[name]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[LifespanContextT, RequestT],
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by name with arguments."""
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        return await tool.run(arguments, context, convert_result=convert_result)
