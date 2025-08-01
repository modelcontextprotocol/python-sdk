from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.shared.context import LifespanContextT, RequestT
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT

logger = get_logger(__name__)


class ToolManager:
    """Manages FastMCP tools."""

    def __init__(
        self,
        warn_on_duplicate_tools: bool = True,
        *,
        tools: list[Tool] | None = None,
    ):
        self._tools: dict[str, Tool] = {}
        if tools is not None:
            for tool in tools:
                if warn_on_duplicate_tools and tool.uri in self._tools:
                    logger.warning(f"Tool already exists: {tool.uri}")
                self._tools[tool.uri] = tool

        self.warn_on_duplicate_tools = warn_on_duplicate_tools

    def _normalize_to_uri(self, name_or_uri: str) -> str:
        """Convert name to URI if needed."""
        if name_or_uri.startswith("tool://"):
            return name_or_uri
        return f"tool://{name_or_uri}"

    def get_tool(self, name: str) -> Tool | None:
        """Get tool by name or URI."""
        uri = self._normalize_to_uri(name)
        return self._tools.get(uri)

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
        structured_output: bool | None = None,
    ) -> Tool:
        """Add a tool to the server."""
        tool = Tool.from_function(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
        )
        existing = self._tools.get(tool.uri)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.uri}")
            return existing
        self._tools[tool.uri] = tool
        return tool

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by name with arguments."""
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        return await tool.run(arguments, context=context, convert_result=convert_result)
