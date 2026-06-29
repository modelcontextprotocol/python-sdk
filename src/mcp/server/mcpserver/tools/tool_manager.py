from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp_types import Icon, ToolAnnotations

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.logging import get_logger

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context

logger = get_logger(__name__)


class ToolManager:
    """Manages MCPServer tools."""

    def __init__(self, warn_on_duplicate_tools: bool = True, *, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or ():
            if warn_on_duplicate_tools and tool.name in self._tools:
                logger.warning(f"Tool already exists: {tool.name}")
            self._tools[tool.name] = tool

        self.warn_on_duplicate_tools = warn_on_duplicate_tools

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Tool:
        """Register a tool built from `fn`; if the name is already registered, return the existing tool unchanged."""
        tool = Tool.from_function(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )
        existing = self._tools.get(tool.name)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.name}")
            return existing
        self._tools[tool.name] = tool
        return tool

    def remove_tool(self, name: str) -> None:
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
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        return await tool.run(arguments, context, convert_result=convert_result)
