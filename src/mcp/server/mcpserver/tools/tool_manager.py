from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.logging import get_logger
from mcp.types import Icon, ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.server import Context

logger = get_logger(__name__)


class ToolManager:
    """Manages MCPServer tools."""

    def __init__(
        self,
        warn_on_duplicate_tools: bool = True,
        *,
        tools: list[Tool] | None = None,
        dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None,
    ):
        self._tools: dict[str, Tool] = {}
        if tools is not None:
            for tool in tools:
                if warn_on_duplicate_tools and tool.name in self._tools:
                    logger.warning(f"Tool already exists: {tool.name}")
                self._tools[tool.name] = tool

        self.warn_on_duplicate_tools = warn_on_duplicate_tools
        self.dependency_overrides = dependency_overrides if dependency_overrides is not None else {}

    def get_tool(self, name: str) -> Tool | None:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
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
        """Add a tool to the server."""
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
        """Remove a tool by name."""
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        del self._tools[name]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by name with arguments."""
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        # Create dependency resolver if tool has dependencies
        dependency_resolver = None
        if tool.dependency_kwarg_names:
            from mcp.server.mcpserver.utilities.dependency_resolver import DependencyResolver

            dependency_resolver = DependencyResolver(context=context, overrides=self.dependency_overrides)

        return await tool.run(
            arguments, context=context, convert_result=convert_result, dependency_resolver=dependency_resolver
        )
