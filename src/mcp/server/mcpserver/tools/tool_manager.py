from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.logging import get_logger
from mcp.types import Icon, ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context

logger = get_logger(__name__)


class ToolManager:
    """Manages MCPServer tools with optional tenant-scoped storage.

    Tools are stored in a nested dict: ``{tenant_id: {tool_name: Tool}}``.
    This allows the same tool name to exist independently under different
    tenants with O(1) lookups per tenant. When ``tenant_id`` is ``None``
    (the default), tools live in a global scope, preserving backward
    compatibility with single-tenant usage.

    Note: This class is not thread-safe. It is designed to run within a
    single-threaded async event loop, where all synchronous mutations
    execute atomically. Do not share instances across OS threads without
    external synchronization.
    """

    def __init__(
        self,
        warn_on_duplicate_tools: bool = True,
        *,
        tools: list[Tool] | None = None,
    ):
        self._tools: dict[str | None, dict[str, Tool]] = {}
        if tools is not None:
            scope = self._tools.setdefault(None, {})
            for tool in tools:
                if warn_on_duplicate_tools and tool.name in scope:
                    logger.warning(f"Tool already exists: {tool.name}")
                scope[tool.name] = tool

        self.warn_on_duplicate_tools = warn_on_duplicate_tools

    def get_tool(self, name: str, *, tenant_id: str | None = None) -> Tool | None:
        """Get tool by name, optionally scoped to a tenant."""
        return self._tools.get(tenant_id, {}).get(name)

    def list_tools(self, *, tenant_id: str | None = None) -> list[Tool]:
        """List all registered tools for a given tenant scope."""
        return list(self._tools.get(tenant_id, {}).values())

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
        *,
        tenant_id: str | None = None,
    ) -> Tool:
        """Add a tool to the server, optionally scoped to a tenant."""
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
        scope = self._tools.setdefault(tenant_id, {})
        existing = scope.get(tool.name)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.name}")
            return existing
        scope[tool.name] = tool
        return tool

    def remove_tool(self, name: str, *, tenant_id: str | None = None) -> None:
        """Remove a tool by name, optionally scoped to a tenant."""
        scope = self._tools.get(tenant_id, {})
        if name not in scope:
            raise ToolError(f"Unknown tool: {name}")
        del scope[name]
        if not scope and tenant_id in self._tools:
            del self._tools[tenant_id]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[LifespanContextT, RequestT],
        convert_result: bool = False,
        *,
        tenant_id: str | None = None,
    ) -> Any:
        """Call a tool by name with arguments, optionally scoped to a tenant."""
        tool = self.get_tool(name, tenant_id=tenant_id)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        return await tool.run(arguments, context, convert_result=convert_result)
