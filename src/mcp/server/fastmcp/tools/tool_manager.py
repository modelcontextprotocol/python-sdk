from __future__ import annotations as _annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.shared.context import LifespanContextT
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.fastmcp.resources.resource_manager import ResourceManager
    from mcp.server.session import ServerSessionT

logger = get_logger(__name__)


class ToolManager:
    """Manages FastMCP tools."""

    def __init__(self, warn_on_duplicate_tools: bool = True):
        self._tools: dict[str, Tool] = {}
        self.warn_on_duplicate_tools = warn_on_duplicate_tools
        self._resource_manager = None

    def get_tool(self, name: str) -> Tool | None:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())
        
    def set_resource_manager(self, resource_manager: ResourceManager) -> None:
        """Set the resource manager reference.
        
        Args:
            resource_manager: The ResourceManager instance
        """
        self._resource_manager = resource_manager

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        async_supported: bool = False,
    ) -> Tool:
        """Add a tool to the server."""
        tool = Tool.from_function(
            fn, name=name, description=description, annotations=annotations,
            async_supported=async_supported
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
        context: Context[ServerSessionT, LifespanContextT] | None = None,
    ) -> Any:
        """Call a tool by name with arguments."""
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")
            
        # Check if the tool supports async execution
        if tool.async_supported and self._resource_manager:
            # Create an async resource
            resource = self._resource_manager.create_async_resource(
                name=tool.name,
                description=tool.description,
            )
            
            # Set the resource in the context if provided
            if context:
                context.resource = resource
            
            # Create a task to run the tool
            async def run_tool_async():
                try:
                    # Run the tool
                    result = await tool.run(arguments, context=context)
                    
                    # Mark the resource as completed
                    await resource.complete()
                    
                    return result
                except Exception as e:
                    # Mark the resource as failed
                    await resource.fail(str(e))
                    raise
                    
            # Create and start the task
            task = asyncio.create_task(run_tool_async())
            
            # Start the resource
            await resource.start(task)
            
            # Return the resource URI
            return {
                "type": "resource",
                "uri": str(resource.uri),
                "status": resource.status.value,
            }
        else:
            # Run the tool synchronously
            return await tool.run(arguments, context=context)
