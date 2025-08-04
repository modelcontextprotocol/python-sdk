from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, overload

from pydantic import AnyUrl

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.uri_utils import filter_by_uri_paths, normalize_to_tool_uri
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
                if warn_on_duplicate_tools and str(tool.uri) in self._tools:
                    logger.warning(f"Tool already exists: {tool.uri}")
                self._tools[str(tool.uri)] = tool

        self.warn_on_duplicate_tools = warn_on_duplicate_tools

    def _normalize_to_uri(self, name_or_uri: str) -> str:
        """Convert name to URI if needed."""
        return normalize_to_tool_uri(name_or_uri)

    @overload
    def get_tool(self, name_or_uri: str) -> Tool | None:
        """Get tool by name."""
        ...

    @overload
    def get_tool(self, name_or_uri: AnyUrl) -> Tool | None:
        """Get tool by URI."""
        ...

    def get_tool(self, name_or_uri: AnyUrl | str) -> Tool | None:
        """Get tool by name or URI."""
        if isinstance(name_or_uri, AnyUrl):
            return self._tools.get(str(name_or_uri))

        # Try as a direct URI first
        if name_or_uri in self._tools:
            return self._tools[name_or_uri]

        # Try to find a tool by name
        for tool in self._tools.values():
            if tool.name == name_or_uri:
                return tool

        # Finally try normalizing to URI
        uri = self._normalize_to_uri(name_or_uri)
        return self._tools.get(uri)

    def list_tools(self, uri_paths: list[AnyUrl] | None = None) -> list[Tool]:
        """List all registered tools, optionally filtered by URI paths."""
        tools = list(self._tools.values())
        if uri_paths:
            tools = filter_by_uri_paths(tools, uri_paths)
        logger.debug("Listing tools", extra={"count": len(tools), "uri_paths": uri_paths})
        return tools

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        uri: str | AnyUrl | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        structured_output: bool | None = None,
    ) -> Tool:
        """Add a tool to the server."""
        tool = Tool.from_function(
            fn,
            name=name,
            uri=uri,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
        )
        existing = self._tools.get(str(tool.uri))
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.uri}")
            return existing
        self._tools[str(tool.uri)] = tool
        return tool

    @overload
    async def call_tool(
        self,
        name_or_uri: str,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by name with arguments."""
        ...

    @overload
    async def call_tool(
        self,
        name_or_uri: AnyUrl,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by URI with arguments."""
        ...

    async def call_tool(
        self,
        name_or_uri: AnyUrl | str,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by name or URI with arguments."""
        tool = self.get_tool(name_or_uri)
        if not tool:
            raise ToolError(f"Unknown tool: {name_or_uri}")

        return await tool.run(arguments, context=context, convert_result=convert_result)
