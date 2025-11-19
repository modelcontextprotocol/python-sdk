"""Unified primitive group for programmatic progressive discovery.

This module provides ToolGroup class that allows servers to define groups
containing tools, prompts, and resources together, all discoverable through
progressive disclosure following the same pattern.

Supports nested tool groups for hierarchical organization.
"""

from __future__ import annotations

from mcp.types import Prompt, Resource, Tool


class ToolGroup:
    """A semantic group of related tools, prompts, and resources for progressive discovery.

    ToolGroups allow organizing all MCP primitives by domain (math, weather, github, etc.)
    and enabling progressive disclosure - gateways are shown initially, and
    actual primitives are loaded on-demand when the gateway is called.

    Supports nested ToolGroups for hierarchical organization. Can contain
    a mix of MCP Tool, Prompt, Resource objects and nested ToolGroup objects.

    Attributes:
        name: Unique identifier for the group (e.g., "math", "weather")
        description: Description of the group's purpose
        tools: List of MCP Tool objects or nested ToolGroup objects
        prompts: List of MCP Prompt objects in this group
        resources: List of MCP Resource objects in this group
    """

    def __init__(
        self,
        name: str,
        description: str,
        tools: list[Tool | ToolGroup] | None = None,
        prompts: list[Prompt] | None = None,
        resources: list[Resource] | None = None,
    ):
        """Initialize a ToolGroup with tools, prompts, and resources.

        Args:
            name: Unique identifier for the group
            description: Description of what this group provides
            tools: List of MCP Tool objects or nested ToolGroup objects
            prompts: List of MCP Prompt objects in this group
            resources: List of MCP Resource objects in this group
        """
        self.name = name
        self.description = description
        self.tools = tools or []
        self.prompts = prompts or []
        self.resources = resources or []

    def get_tool(self, tool_name: str) -> Tool | None:
        """Get a specific tool from this group by name (recursive search).

        Args:
            tool_name: Name of the tool to retrieve

        Returns:
            Tool if found, None otherwise (searches recursively through nested groups)
        """
        for item in self.tools:
            if isinstance(item, Tool):
                if item.name == tool_name:
                    return item
            elif isinstance(item, ToolGroup):
                result = item.get_tool(tool_name)
                if result is not None:
                    return result
        return None

    def get_prompt(self, prompt_name: str) -> Prompt | None:
        """Get a specific prompt from this group by name.

        Args:
            prompt_name: Name of the prompt to retrieve

        Returns:
            Prompt if found, None otherwise
        """
        for prompt in self.prompts:
            if prompt.name == prompt_name:
                return prompt
        return None

    def get_resource(self, uri: str) -> Resource | None:
        """Get a specific resource from this group by URI.

        Args:
            uri: URI of the resource to retrieve

        Returns:
            Resource if found, None otherwise
        """
        for resource in self.resources:
            if str(resource.uri) == uri:
                return resource
        return None
