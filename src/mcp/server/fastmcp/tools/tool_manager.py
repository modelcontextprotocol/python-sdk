from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.fastmcp.utilities.versioning import VersionConstraintError, validate_tool_requirements
from mcp.shared.context import LifespanContextT, RequestT
from mcp.types import Icon, ToolAnnotations, UNSATISFIED_TOOL_VERSION

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
        # Store tools by name -> list of versions
        self._tools: dict[str, list[Tool]] = {}
        if tools is not None:
            for tool in tools:
                self._add_tool_internal(tool, warn_on_duplicate_tools)

        self.warn_on_duplicate_tools = warn_on_duplicate_tools

    def _add_tool_internal(self, tool: Tool, warn_on_duplicate: bool) -> None:
        """Internal method to add a tool."""
        if tool.name not in self._tools:
            self._tools[tool.name] = []
        
        # Check for duplicate versions
        existing_versions = [t.version for t in self._tools[tool.name] if t.version is not None]
        if tool.version in existing_versions:
            if warn_on_duplicate:
                logger.warning(f"Tool version already exists: {tool.name} {tool.version}")
            return
        
        self._tools[tool.name].append(tool)

    def get_tool(self, name: str, version: str | None = None) -> Tool | None:
        """Get tool by name and optionally version."""
        if name not in self._tools:
            return None
        
        tool_versions = self._tools[name]
        
        if version is None:
            # Return the latest stable version, or latest prerelease if no stable versions
            stable_versions = [t for t in tool_versions if t.version is None or not self._is_prerelease(t.version)]
            if stable_versions:
                return max(stable_versions, key=lambda t: self._parse_version_for_sorting(t.version))
            else:
                return max(tool_versions, key=lambda t: self._parse_version_for_sorting(t.version))
        
        # Find exact version match
        for tool in tool_versions:
            if tool.version == version:
                return tool
        
        return None

    def _is_prerelease(self, version: str | None) -> bool:
        """Check if a version is a prerelease."""
        if version is None:
            return False
        return '-' in version

    def _parse_version_for_sorting(self, version: str | None) -> tuple[int, int, int, str]:
        """Parse version for sorting purposes."""
        if version is None:
            return (0, 0, 0, "")
        
        try:
            from mcp.server.fastmcp.utilities.versioning import parse_version
            major, minor, patch, prerelease = parse_version(version)
            return (major, minor, patch, prerelease or "")
        except Exception:
            return (0, 0, 0, version)

    def list_tools(self) -> list[Tool]:
        """List all registered tools (latest version of each)."""
        result = []
        for tool_name in self._tools:
            tool = self.get_tool(tool_name)
            if tool:
                result.append(tool)
        return result

    def get_available_versions(self, name: str) -> list[str]:
        """Get all available versions for a tool."""
        if name not in self._tools:
            return []
        return [tool.version for tool in self._tools[name] if tool.version is not None]

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        version: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
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
            structured_output=structured_output,
        )
        # Set the version if provided
        if version is not None:
            tool.version = version
        
        self._add_tool_internal(tool, self.warn_on_duplicate_tools)
        return tool

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        tool_requirements: dict[str, str] | None = None,
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Call a tool by name with arguments and optional version requirements."""
        # Validate tool requirements if provided
        if tool_requirements:
            available_tools = {name: self.get_available_versions(name) for name in tool_requirements}
            try:
                selected_versions = validate_tool_requirements(tool_requirements, available_tools)
                # Use the selected version for the requested tool
                if name in selected_versions:
                    tool = self.get_tool(name, selected_versions[name])
                else:
                    tool = self.get_tool(name)
            except VersionConstraintError as e:
                # Convert to ToolError with specific error code
                error = ToolError(str(e))
                error.code = UNSATISFIED_TOOL_VERSION
                raise error
        else:
            tool = self.get_tool(name)
        
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        return await tool.run(arguments, context=context, convert_result=convert_result)
