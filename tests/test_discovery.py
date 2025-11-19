"""Tests for progressive disclosure discovery system.

Tests the ToolGroup, ToolGroupManager, and Server integration
for progressive disclosure of tools, prompts, and resources.
"""

import pytest

from mcp.server.discovery import ToolGroup, ToolGroupManager
from mcp.server.lowlevel.server import Server
from mcp.types import Prompt, PromptArgument, Resource, Tool


@pytest.fixture
def math_tool() -> Tool:
    """Create a simple math tool for testing."""
    return Tool(
        name="add",
        description="Add two numbers",
        inputSchema={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    )


@pytest.fixture
def weather_tool() -> Tool:
    """Create a simple weather tool for testing."""
    return Tool(
        name="get_forecast",
        description="Get weather forecast",
        inputSchema={"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]},
    )


@pytest.fixture
def math_prompt() -> Prompt:
    """Create a simple math prompt for testing."""
    return Prompt(
        name="solve_equation",
        description="Solve a mathematical equation",
        arguments=[PromptArgument(name="equation", description="The equation to solve")],
    )


@pytest.fixture
def weather_resource() -> Resource:
    """Create a simple weather resource for testing."""
    from pydantic import AnyUrl

    return Resource(
        uri=AnyUrl("weather://current_conditions"),
        name="current_conditions",
        description="Current weather conditions",
    )


class TestToolGroup:
    """Tests for ToolGroup class."""

    def test_create_basic_tool_group(self, math_tool: Tool):
        """Test creating a basic tool group with tools."""
        group = ToolGroup(name="math", description="Math tools", tools=[math_tool])

        assert group.name == "math"
        assert group.description == "Math tools"
        assert len(group.tools) == 1
        assert group.tools[0].name == "add"
        assert len(group.prompts) == 0
        assert len(group.resources) == 0

    def test_tool_group_with_all_primitives(self, math_tool: Tool, math_prompt: Prompt, weather_resource: Resource):
        """Test creating a tool group with tools, prompts, and resources."""
        group = ToolGroup(
            name="mixed",
            description="Group with all primitives",
            tools=[math_tool],
            prompts=[math_prompt],
            resources=[weather_resource],
        )

        assert group.name == "mixed"
        assert len(group.tools) == 1
        assert len(group.prompts) == 1
        assert len(group.resources) == 1

    def test_get_tool_by_name(self, math_tool: Tool, weather_tool: Tool):
        """Test retrieving a tool by name from a group."""
        group = ToolGroup(name="math", description="Math tools", tools=[math_tool, weather_tool])

        found_tool = group.get_tool("add")
        assert found_tool is not None
        assert found_tool.name == "add"

    def test_get_tool_not_found(self, math_tool: Tool):
        """Test that get_tool returns None for non-existent tool."""
        group = ToolGroup(name="math", description="Math tools", tools=[math_tool])

        found_tool = group.get_tool("nonexistent")
        assert found_tool is None

    def test_nested_tool_group(self, math_tool: Tool, weather_tool: Tool):
        """Test nested tool groups."""
        basic_group = ToolGroup(name="basic", description="Basic tools", tools=[math_tool])
        advanced_group = ToolGroup(name="advanced", description="Advanced tools", tools=[weather_tool])

        parent_group = ToolGroup(
            name="science",
            description="Science tools",
            tools=[basic_group, advanced_group],
        )

        assert parent_group.name == "science"
        assert len(parent_group.tools) == 2
        # First item should be a ToolGroup
        assert isinstance(parent_group.tools[0], ToolGroup)

    def test_get_tool_in_nested_group(self, math_tool: Tool, weather_tool: Tool):
        """Test retrieving a tool from a nested group."""
        basic_group = ToolGroup(name="basic", description="Basic tools", tools=[math_tool])
        advanced_group = ToolGroup(name="advanced", description="Advanced tools", tools=[weather_tool])

        parent_group = ToolGroup(
            name="science",
            description="Science tools",
            tools=[basic_group, advanced_group],
        )

        # Find tool in nested group
        found_tool = parent_group.get_tool("add")
        assert found_tool is not None
        assert found_tool.name == "add"

        found_tool = parent_group.get_tool("get_forecast")
        assert found_tool is not None
        assert found_tool.name == "get_forecast"

    def test_get_prompt_by_name(self, math_prompt: Prompt):
        """Test retrieving a prompt by name from a group."""
        group = ToolGroup(name="math", description="Math tools", prompts=[math_prompt])

        found_prompt = group.get_prompt("solve_equation")
        assert found_prompt is not None
        assert found_prompt.name == "solve_equation"

    def test_get_prompt_not_found(self, math_prompt: Prompt):
        """Test that get_prompt returns None for non-existent prompt."""
        group = ToolGroup(name="math", description="Math tools", prompts=[math_prompt])

        found_prompt = group.get_prompt("nonexistent")
        assert found_prompt is None

    def test_get_resource_by_uri(self, weather_resource: Resource):
        """Test retrieving a resource by URI from a group."""
        group = ToolGroup(name="weather", description="Weather tools", resources=[weather_resource])

        found_resource = group.get_resource("weather://current_conditions")
        assert found_resource is not None
        assert str(found_resource.uri) == "weather://current_conditions"

    def test_get_resource_not_found(self, weather_resource: Resource):
        """Test that get_resource returns None for non-existent resource."""
        group = ToolGroup(name="weather", description="Weather tools", resources=[weather_resource])

        found_resource = group.get_resource("nonexistent://uri")
        assert found_resource is None


class TestToolGroupManager:
    """Tests for ToolGroupManager class."""

    def test_create_manager_with_groups(self, math_tool: Tool, weather_tool: Tool):
        """Test creating a manager with tool groups."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        weather_group = ToolGroup(name="weather", description="Weather data", tools=[weather_tool])

        manager = ToolGroupManager(groups=[math_group, weather_group])

        assert len(manager.groups) == 2
        assert manager.get_group_names() == ["math", "weather"]

    def test_get_group_names(self, math_tool: Tool, weather_tool: Tool):
        """Test retrieving all group names."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        weather_group = ToolGroup(name="weather", description="Weather data", tools=[weather_tool])

        manager = ToolGroupManager(groups=[math_group, weather_group])

        assert set(manager.get_group_names()) == {"math", "weather"}

    def test_get_group_description(self, math_tool: Tool):
        """Test retrieving group description."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        manager = ToolGroupManager(groups=[math_group])

        description = manager.get_group_description("math")
        assert description == "Math operations"

    def test_get_group_description_not_found(self, math_tool: Tool):
        """Test that get_group_description returns empty string for non-existent group."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        manager = ToolGroupManager(groups=[math_group])

        description = manager.get_group_description("nonexistent")
        assert description == ""

    def test_gateway_tool_name_generation(self, math_tool: Tool):
        """Test that gateway tool names are generated correctly."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        manager = ToolGroupManager(groups=[math_group])

        # Gateway tools mapping should exist (gateway name is same as group name)
        assert "math" in manager._gateway_tools
        assert manager._gateway_tools["math"] == "math"

    def test_get_group_tools(self, math_tool: Tool, weather_tool: Tool):
        """Test retrieving all tools for a specific group."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool, weather_tool])
        manager = ToolGroupManager(groups=[math_group])

        tools = manager.get_group_tools("math")
        assert len(tools) == 2
        assert tools[0]["name"] == "add"
        assert tools[1]["name"] == "get_forecast"

    def test_get_group_tools_nonexistent(self, math_tool: Tool):
        """Test that get_group_tools returns empty list for non-existent group."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        manager = ToolGroupManager(groups=[math_group])

        tools = manager.get_group_tools("nonexistent")
        assert tools == []

    def test_get_group_prompts(self, math_prompt: Prompt):
        """Test retrieving all prompts for a specific group."""
        math_group = ToolGroup(name="math", description="Math operations", prompts=[math_prompt])
        manager = ToolGroupManager(groups=[math_group])

        prompts = manager.get_group_prompts("math")
        assert len(prompts) == 1
        assert prompts[0]["name"] == "solve_equation"

    def test_get_group_resources(self, weather_resource: Resource):
        """Test retrieving all resources for a specific group."""
        weather_group = ToolGroup(name="weather", description="Weather data", resources=[weather_resource])
        manager = ToolGroupManager(groups=[weather_group])

        resources = manager.get_group_resources("weather")
        assert len(resources) == 1
        assert str(resources[0]["uri"]) == "weather://current_conditions"

    def test_nested_group_gateway_tools(self, math_tool: Tool, weather_tool: Tool):
        """Test that nested groups also generate gateway tools."""
        basic_group = ToolGroup(name="basic", description="Basic operations", tools=[math_tool])
        advanced_group = ToolGroup(name="advanced", description="Advanced operations", tools=[weather_tool])

        parent_group = ToolGroup(
            name="science",
            description="Science tools",
            tools=[basic_group, advanced_group],
        )

        manager = ToolGroupManager(groups=[parent_group])

        # All groups should have gateway tools (top-level and nested)
        # Gateway tool names are the same as group names
        assert "science" in manager._gateway_tools
        assert "basic" in manager._gateway_tools
        assert "advanced" in manager._gateway_tools


class TestServerDiscoveryIntegration:
    """Tests for Server integration with discovery system."""

    def test_discovery_disabled_by_default(self):
        """Test that discovery is disabled by default."""
        server = Server("test")
        assert server.is_discovery_enabled is False

    def test_enable_discovery_sets_flag(self, math_tool: Tool):
        """Test that registering discovery tools enables discovery."""
        server = Server("test")
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        manager = ToolGroupManager(groups=[math_group])

        server.register_discovery_tools(manager)

        assert server.is_discovery_enabled is True

    def test_register_discovery_tools_stores_manager(self, math_tool: Tool):
        """Test that register_discovery_tools stores the manager."""
        server = Server("test")
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        manager = ToolGroupManager(groups=[math_group])

        server.register_discovery_tools(manager)

        assert server._discovery is manager

    def test_enable_discovery_with_groups(self, math_tool: Tool, weather_tool: Tool):
        """Test the enable_discovery_with_groups convenience method."""
        server = Server("test")

        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        weather_group = ToolGroup(name="weather", description="Weather data", tools=[weather_tool])

        server.enable_discovery_with_groups([math_group, weather_group])

        assert server.is_discovery_enabled is True
        assert server._discovery is not None
        assert set(server._discovery.get_group_names()) == {"math", "weather"}

    def test_enable_discovery_with_single_group(self, math_tool: Tool):
        """Test enable_discovery_with_groups with single group."""
        server = Server("test")
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])

        server.enable_discovery_with_groups([math_group])

        assert server.is_discovery_enabled is True
        assert server._discovery is not None
        assert server._discovery.get_group_names() == ["math"]

    def test_enable_discovery_multiple_times(self, math_tool: Tool):
        """Test that calling enable_discovery_with_groups multiple times updates groups."""
        server = Server("test")

        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        server.enable_discovery_with_groups([math_group])

        assert server.is_discovery_enabled is True
        assert server._discovery is not None
        assert len(server._discovery.groups) == 1

        # Enable again with different groups
        weather_tool = Tool(
            name="forecast",
            description="Get forecast",
            inputSchema={"type": "object"},
        )
        weather_group = ToolGroup(name="weather", description="Weather data", tools=[weather_tool])
        server.enable_discovery_with_groups([weather_group])

        assert server._discovery is not None
        assert len(server._discovery.groups) == 1
        assert server._discovery.get_group_names() == ["weather"]

    def test_discovery_manager_tracks_groups(self, math_tool: Tool, weather_tool: Tool):
        """Test that discovery manager properly tracks groups."""
        math_group = ToolGroup(name="math", description="Math operations", tools=[math_tool])
        weather_group = ToolGroup(name="weather", description="Weather data", tools=[weather_tool])

        server = Server("test")
        server.enable_discovery_with_groups([math_group, weather_group])

        # Verify manager has all groups
        assert server._discovery is not None
        assert len(server._discovery.groups) == 2
        assert set(server._discovery.get_group_names()) == {"math", "weather"}

    def test_discovery_with_nested_groups(self, math_tool: Tool, weather_tool: Tool):
        """Test discovery with nested tool groups."""
        basic_group = ToolGroup(name="basic", description="Basic operations", tools=[math_tool])
        advanced_group = ToolGroup(name="advanced", description="Advanced operations", tools=[weather_tool])
        parent_group = ToolGroup(
            name="science",
            description="Science tools",
            tools=[basic_group, advanced_group],
        )

        server = Server("test")
        server.enable_discovery_with_groups([parent_group])

        assert server.is_discovery_enabled is True
        # Only top-level group should be in groups list
        assert server._discovery is not None
        assert len(server._discovery.groups) == 1
        assert server._discovery.get_group_names() == ["science"]
        # But all groups (including nested) should be in gateway tools mapping
        assert "science" in server._discovery._gateway_tools
        assert "basic" in server._discovery._gateway_tools
        assert "advanced" in server._discovery._gateway_tools
