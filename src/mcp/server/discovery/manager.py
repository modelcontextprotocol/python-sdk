"""Tool Group Manager for progressive disclosure of tools.

This module provides the ToolGroupManager class which manages tool groups
and returns tool definitions on demand.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.discovery.tool_group import ToolGroup

logger = logging.getLogger(__name__)


class ToolGroupManager:
    """Manages tool groups and returns tools on demand.

    Works with ToolGroup objects to provide progressive disclosure of tools.
    Tool groups are defined programmatically in Python with no filesystem dependencies.

    Attributes:
        groups: List of ToolGroup objects
        _gateway_tools: Mapping of gateway tool names to group names (built on init)
    """

    def __init__(self, groups: list[ToolGroup]) -> None:
        """Initialize the manager with a list of tool groups.

        Args:
            groups: List of ToolGroup objects defining tool groups
        """
        self.groups = groups
        # Build explicit registry of gateway tool names to group names
        self._gateway_tools = self._build_gateway_tools()

    def _build_gateway_tools(self) -> dict[str, str]:
        """Build explicit registry of gateway tool names to group names.

        Recursively builds a mapping including both top-level and nested groups.
        For example, if you have a "math" group and a nested "advanced" group inside it,
        this will create entries for both "get_math_tools" and "get_advanced_tools".

        Returns:
            Dict mapping gateway tool names to their group names.
            E.g., {"get_math_tools": "math", "get_weather_tools": "weather"}
        """
        gateways: dict[str, str] = {}

        def add_group_and_nested(group: ToolGroup) -> None:
            """Recursively add group and its nested groups to registry."""
            gateway_name = self._gateway_tool_name(group.name)
            gateways[gateway_name] = group.name

            # Check for nested groups within this group's tools
            for item in group.tools:
                if hasattr(item, "name") and hasattr(item, "description") and hasattr(item, "tools"):
                    # This is a nested ToolGroup - add it recursively
                    add_group_and_nested(item)

        for group in self.groups:
            add_group_and_nested(group)

        return gateways

    def get_group_names(self) -> list[str]:
        """Get names of all top-level groups.

        Returns:
            List of group names (top-level only, not nested)
        """
        return [g.name for g in self.groups]

    def get_group_description(self, group_name: str) -> str:
        """Get description for a group.

        Args:
            group_name: The name of the group

        Returns:
            Group description, or empty string if not found
        """
        for group in self.groups:
            if group.name == group_name:
                return group.description
        return ""

    def _find_group_recursive(self, group_name: str, groups: list[ToolGroup] | None = None) -> ToolGroup | None:
        """Find a group by name, searching recursively through nested groups.

        Args:
            group_name: The name of the group to find
            groups: The groups to search in (defaults to self.groups)

        Returns:
            The ToolGroup if found, None otherwise
        """
        if groups is None:
            groups = self.groups

        for group in groups:
            if group.name == group_name:
                return group
            # Search recursively in nested groups
            for item in group.tools:
                if hasattr(item, "name") and hasattr(item, "tools"):
                    # This is a nested ToolGroup
                    result = self._find_group_recursive(group_name, [item])
                    if result:
                        return result
        return None

    def get_group_tools(self, group_name: str) -> list[dict[str, Any]]:
        """Get tool definitions for a specific group.

        If the group contains nested ToolGroups, returns gateway tools for those
        sub-groups instead of flattening. This allows the LLM to decide which
        sub-groups to load progressively.

        For leaf groups (containing only Tool objects), returns the actual tools.

        Args:
            group_name: The name of the group to retrieve tools from

        Returns:
            List of tool/gateway tool definitions from the group.
            Empty list if group not found.
        """
        group = self._find_group_recursive(group_name)
        if not group:
            return []

        result: list[dict[str, Any]] = []
        for item in group.tools:
            # If it's a nested ToolGroup, return a gateway tool for it
            if hasattr(item, "name") and hasattr(item, "description") and hasattr(item, "tools"):
                # This is a nested ToolGroup - return as gateway tool
                # Mark with x-gateway: True so client discovery code identifies it as a gateway
                result.append(
                    {
                        "name": self._gateway_tool_name(item.name),
                        "description": item.description,
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                            "x-gateway": True,  # Explicit marker for gateway tools
                        },
                    }
                )
            else:
                # This is a Tool - return its definition
                result.append(item.model_dump(exclude_unset=True))
        return result

    def get_group_prompts(self, group_name: str) -> list[dict[str, Any]]:
        """Get prompt definitions for a specific group.

        Args:
            group_name: The name of the group to retrieve prompts from

        Returns:
            List of prompt definitions from the group.
            Empty list if group not found.
        """
        group = self._find_group_recursive(group_name)
        if not group:
            return []

        return [prompt.model_dump(exclude_unset=True) for prompt in group.prompts]

    def get_group_resources(self, group_name: str) -> list[dict[str, Any]]:
        """Get resource definitions for a specific group.

        Args:
            group_name: The name of the group to retrieve resources from

        Returns:
            List of resource definitions from the group.
            Empty list if group not found.
        """
        group = self._find_group_recursive(group_name)
        if not group:
            return []

        return [resource.model_dump(exclude_unset=True) for resource in group.resources]

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Get all tools from all groups.

        Returns:
            Flat list of all tool definitions from all groups
        """
        all_tools: list[dict[str, Any]] = []
        for group_name in self.get_group_names():
            tools = self.get_group_tools(group_name)
            all_tools.extend(tools)
        return all_tools

    def is_gateway_tool(self, tool_name: str) -> bool:
        """Check if a tool name is a gateway tool.

        Uses explicit registry lookup instead of string pattern matching.
        Correctly identifies gateways for both top-level and nested groups,
        without risk of collision with legitimate tools named get_*_tools.

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if the tool is a registered gateway tool, False otherwise
        """
        return tool_name in self._gateway_tools

    def extract_group_name(self, gateway_tool_name: str) -> str | None:
        """Extract group name from a gateway tool name.

        Converts "get_repo_management_tools" to "repo_management".
        Uses registry lookup instead of string slicing.

        Args:
            gateway_tool_name: The name of the gateway tool

        Returns:
            The extracted group name, or None if tool is not a registered
            gateway tool
        """
        return self._gateway_tools.get(gateway_tool_name)

    def find_prompt_in_groups(self, prompt_name: str, loaded_groups: set[str]) -> dict[str, Any] | None:
        """Find a prompt in loaded groups.

        Args:
            prompt_name: Name of the prompt to find
            loaded_groups: Set of group names that have been loaded

        Returns:
            Prompt definition dict if found, None otherwise
        """
        for group_name in loaded_groups:
            prompts = self.get_group_prompts(group_name)
            for prompt in prompts:
                if prompt.get("name") == prompt_name:
                    return prompt
        return None

    def find_resource_in_groups(self, uri: str | Any, loaded_groups: set[str]) -> dict[str, Any] | None:
        """Find a resource in loaded groups by URI.

        Args:
            uri: URI of the resource to find (str or AnyUrl)
            loaded_groups: Set of group names that have been loaded

        Returns:
            Resource definition dict if found, None otherwise
        """
        uri_str = str(uri)
        for group_name in loaded_groups:
            resources = self.get_group_resources(group_name)
            for resource in resources:
                if str(resource.get("uri")) == uri_str:
                    return resource
        return None

    def get_prompts_from_loaded_groups(self, loaded_groups: set[str]) -> list[dict[str, Any]]:
        """Get all prompts from loaded groups.

        Args:
            loaded_groups: Set of group names that have been loaded

        Returns:
            List of prompt definitions from loaded groups
        """
        all_prompts: list[dict[str, Any]] = []
        for group_name in loaded_groups:
            prompts = self.get_group_prompts(group_name)
            all_prompts.extend(prompts)
        return all_prompts

    def get_resources_from_loaded_groups(self, loaded_groups: set[str]) -> list[dict[str, Any]]:
        """Get all resources from loaded groups.

        Args:
            loaded_groups: Set of group names that have been loaded

        Returns:
            List of resource definitions from loaded groups
        """
        all_resources: list[dict[str, Any]] = []
        for group_name in loaded_groups:
            resources = self.get_group_resources(group_name)
            all_resources.extend(resources)
        return all_resources

    @staticmethod
    def _gateway_tool_name(group_name: str) -> str:
        """Generate gateway tool name from group name.

        Gateway tools are now named directly after the group they represent.
        This is cleaner and removes the need for the "get_*_tools" naming pattern.

        Args:
            group_name: The group name

        Returns:
            Gateway tool name (same as group name)
        """
        return group_name
