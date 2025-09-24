from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import InvocationMode, Tool
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
                if warn_on_duplicate_tools and tool.name in self._tools:
                    logger.warning(f"Tool already exists: {tool.name}")
                self._tools[tool.name] = tool

        self.warn_on_duplicate_tools = warn_on_duplicate_tools

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
        structured_output: bool | None = None,
        invocation_modes: list[InvocationMode] | None = None,
        keep_alive: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Tool:
        """Add a tool to the server."""
        # Default to sync mode if no invocation modes specified
        if invocation_modes is None:
            invocation_modes = ["sync"]

        # Set appropriate default keep_alive based on async compatibility
        # if user didn't specify custom keep_alive
        if keep_alive is None and "async" in invocation_modes:
            keep_alive = 3600  # Default for async-compatible tools

        # Validate keep_alive is only used with async-compatible tools
        if keep_alive is not None and "async" not in invocation_modes:
            raise ValueError(
                f"keep_alive parameter can only be used with async-compatible tools. "
                f"Tool '{name or fn.__name__}' has invocation_modes={invocation_modes} "
                f"but specifies keep_alive={keep_alive}. "
                f"Add 'async' to invocation_modes to use keep_alive."
            )

        meta = meta or {}
        if keep_alive is not None:
            meta.update(
                {
                    # default keepalive value is stashed in _meta to pass it to the lowlevel Server
                    # without adding it to the actual protocol-level tool definition
                    "_keep_alive": keep_alive
                }
            )

        tool = Tool.from_function(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
            invocation_modes=invocation_modes,
            meta=meta,
        )
        existing = self._tools.get(tool.name)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.name}")
            return existing
        self._tools[tool.name] = tool
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
