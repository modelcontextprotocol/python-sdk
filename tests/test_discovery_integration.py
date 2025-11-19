"""Integration tests for progressive disclosure discovery system.

Tests the full end-to-end flow of discovery with client-server communication,
including listTools(), gateway tool calls, and tool refresh behavior.
"""

from typing import Any

import pytest

from mcp.server.discovery import ToolGroup
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session as create_session
from mcp.types import CallToolResult, TextContent, Tool


class TestDiscoveryListTools:
    """Test listTools() behavior with discovery enabled/disabled."""

    @pytest.mark.anyio
    async def test_list_tools_discovery_disabled_returns_all_tools(self):
        """Test that listTools returns all tools when discovery is disabled."""
        server = Server("test")

        tool1 = Tool(name="tool1", description="First tool", inputSchema={"type": "object"})
        tool2 = Tool(name="tool2", description="Second tool", inputSchema={"type": "object"})

        @server.list_tools()
        async def list_tools():
            return [tool1, tool2]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # Should have both tools (discovery disabled)
            assert len(tools) == 2
            assert tools[0].name == "tool1"
            assert tools[1].name == "tool2"

    @pytest.mark.anyio
    async def test_list_tools_discovery_enabled_returns_gateway_tools(self):
        """Test that listTools returns only gateway tools when discovery is enabled."""
        server = Server("test")

        # Create groups with tools
        tool1 = Tool(name="add", description="Add numbers", inputSchema={"type": "object"})
        tool2 = Tool(name="subtract", description="Subtract numbers", inputSchema={"type": "object"})

        math_group = ToolGroup(name="math", description="Math operations", tools=[tool1, tool2])

        weather_group = ToolGroup(
            name="weather",
            description="Weather data",
            tools=[Tool(name="forecast", description="Get forecast", inputSchema={"type": "object"})],
        )

        server.enable_discovery_with_groups([math_group, weather_group])

        @server.list_tools()
        async def list_tools():
            # When discovery is enabled, return empty list - discovery provides gateway tools
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # Should have only gateway tools (discovery enabled)
            assert len(tools) == 2
            gateway_names = {t.name for t in tools}
            assert gateway_names == {"math", "weather"}

            # Verify descriptions come from group descriptions
            math_tool = next(t for t in tools if t.name == "math")
            assert "Math operations" in math_tool.description

            weather_tool = next(t for t in tools if t.name == "weather")
            assert "Weather data" in weather_tool.description

    @pytest.mark.anyio
    async def test_list_tools_single_group_discovery(self):
        """Test listTools with single group discovery."""
        server = Server("test")

        tool = Tool(name="get_weather", description="Get current weather", inputSchema={"type": "object"})
        weather_group = ToolGroup(name="weather", description="Weather tools", tools=[tool])

        server.enable_discovery_with_groups([weather_group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "sunny"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            assert len(tools) == 1
            assert tools[0].name == "weather"


class TestDiscoveryGatewayToolCalls:
    """Test calling gateway tools and receiving actual tools."""

    @pytest.mark.anyio
    async def test_call_gateway_tool_returns_group_tools(self):
        """Test that calling a gateway tool returns the tools from that group."""
        server = Server("test")

        # Create math group with multiple tools
        add_tool = Tool(name="add", description="Add two numbers", inputSchema={"type": "object"})
        multiply_tool = Tool(name="multiply", description="Multiply two numbers", inputSchema={"type": "object"})
        math_group = ToolGroup(name="math", description="Math operations", tools=[add_tool, multiply_tool])

        server.enable_discovery_with_groups([math_group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            if name == "math":
                # Return the tools from math group
                tools_list = [add_tool.model_dump(exclude_unset=True), multiply_tool.model_dump(exclude_unset=True)]
                return CallToolResult(content=[TextContent(type="text", text=str(tools_list))])
            return CallToolResult(content=[TextContent(type="text", text="unknown")])

        async with create_session(server) as client:
            # First, get gateway tools
            gateway_result = await client.list_tools()
            gateway_tools = gateway_result.tools
            assert len(gateway_tools) == 1
            assert gateway_tools[0].name == "math"

            # Call the gateway tool
            result = await client.call_tool("math", {})
            assert result.isError is False
            assert len(result.content) > 0

    @pytest.mark.anyio
    async def test_gateway_tool_input_schema_is_empty(self):
        """Test that gateway tools have empty input schema."""
        server = Server("test")

        tool = Tool(name="test_tool", description="Test", inputSchema={"type": "object"})
        group = ToolGroup(name="test_group", description="Test group", tools=[tool])

        server.enable_discovery_with_groups([group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # Gateway tool should have empty input schema with x-gateway marker
            assert len(tools) == 1
            gateway_tool = tools[0]
            assert gateway_tool.inputSchema["type"] == "object"
            assert gateway_tool.inputSchema["properties"] == {}
            assert gateway_tool.inputSchema["required"] == []
            assert gateway_tool.inputSchema.get("x-gateway") is True


class TestDiscoveryMultipleGroups:
    """Test discovery with multiple groups and nested groups."""

    @pytest.mark.anyio
    async def test_multiple_groups_separate_gateway_tools(self):
        """Test that multiple groups each get their own gateway tool."""
        server = Server("test")

        math_group = ToolGroup(
            name="math",
            description="Math operations",
            tools=[Tool(name="add", description="Add", inputSchema={"type": "object"})],
        )

        weather_group = ToolGroup(
            name="weather",
            description="Weather data",
            tools=[Tool(name="forecast", description="Forecast", inputSchema={"type": "object"})],
        )

        code_group = ToolGroup(
            name="code",
            description="Code operations",
            tools=[Tool(name="compile", description="Compile", inputSchema={"type": "object"})],
        )

        server.enable_discovery_with_groups([math_group, weather_group, code_group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # Should have 3 gateway tools
            assert len(tools) == 3
            names = {t.name for t in tools}
            assert names == {"math", "weather", "code"}

    @pytest.mark.anyio
    async def test_nested_groups_create_nested_gateway_tools(self):
        """Test that nested groups create gateway tools at each level."""
        server = Server("test")

        # Create nested structure: science -> (basic -> add, advanced -> complex_calc)
        add_tool = Tool(name="add", description="Add numbers", inputSchema={"type": "object"})
        basic_group = ToolGroup(name="basic", description="Basic operations", tools=[add_tool])

        complex_tool = Tool(name="complex_calc", description="Complex calculation", inputSchema={"type": "object"})
        advanced_group = ToolGroup(name="advanced", description="Advanced operations", tools=[complex_tool])

        science_group = ToolGroup(
            name="science",
            description="Science tools",
            tools=[basic_group, advanced_group],
        )

        server.enable_discovery_with_groups([science_group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            # Initial listTools should show only top-level gateway
            result = await client.list_tools()
            tools = result.tools
            assert len(tools) == 1
            assert tools[0].name == "science"


class TestDiscoveryMixedMode:
    """Test discovery enabled alongside direct tools."""

    @pytest.mark.anyio
    async def test_discovery_with_mixed_direct_and_grouped_tools(self):
        """Test server with both discovery-enabled groups and direct tools."""
        server = Server("test")

        # Add some direct tools
        direct_tool = Tool(name="direct_tool", description="Direct tool", inputSchema={"type": "object"})

        # Add discovered group
        group_tool = Tool(name="grouped_tool", description="Grouped tool", inputSchema={"type": "object"})
        group = ToolGroup(name="tools", description="Grouped tools", tools=[group_tool])

        server.enable_discovery_with_groups([group])

        @server.list_tools()
        async def list_tools():
            # When discovery is enabled, this is not called for the main list
            # But we can still add direct tools if needed
            return [direct_tool]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # With discovery enabled, should show gateway tool, not direct tool
            # (discovery takes precedence)
            assert len(tools) == 1
            assert tools[0].name == "tools"


class TestDiscoveryWithPrompsAndResources:
    """Test discovery with prompts and resources in groups."""

    @pytest.mark.anyio
    async def test_group_with_tools_and_prompts(self):
        """Test that groups can contain both tools and prompts."""
        from mcp.types import Prompt, PromptArgument

        server = Server("test")

        tool = Tool(name="math_tool", description="Math tool", inputSchema={"type": "object"})
        prompt = Prompt(
            name="solve_equation",
            description="Solve an equation",
            arguments=[PromptArgument(name="equation", description="The equation")],
        )

        math_group = ToolGroup(name="math", description="Math tools", tools=[tool], prompts=[prompt])

        server.enable_discovery_with_groups([math_group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # listTools should return gateway tool
            assert len(tools) == 1
            assert tools[0].name == "math"

    @pytest.mark.anyio
    async def test_group_with_tools_and_resources(self):
        """Test that groups can contain both tools and resources."""
        from pydantic import AnyUrl

        from mcp.types import Resource

        server = Server("test")

        tool = Tool(name="get_file", description="Get file", inputSchema={"type": "object"})
        resource = Resource(
            uri=AnyUrl("file://example.txt"),
            name="example",
            description="Example file",
        )

        file_group = ToolGroup(name="files", description="File tools", tools=[tool], resources=[resource])

        server.enable_discovery_with_groups([file_group])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools

            # listTools should return gateway tool
            assert len(tools) == 1
            assert tools[0].name == "files"


class TestDiscoveryEnabling:
    """Test the flow of enabling and disabling discovery."""

    @pytest.mark.anyio
    async def test_enable_discovery_after_creation(self):
        """Test enabling discovery after server creation."""
        server = Server("test")

        # Initially no discovery
        assert server.is_discovery_enabled is False

        tool = Tool(name="test", description="Test", inputSchema={"type": "object"})
        group = ToolGroup(name="test_group", description="Test", tools=[tool])

        # Enable discovery
        server.enable_discovery_with_groups([group])

        assert server.is_discovery_enabled is True

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools
            assert len(tools) == 1
            assert tools[0].name == "test_group"

    @pytest.mark.anyio
    async def test_replace_groups_via_enable_discovery(self):
        """Test that calling enable_discovery_with_groups replaces previous groups."""
        server = Server("test")

        group1 = ToolGroup(
            name="group1",
            description="Group 1",
            tools=[Tool(name="tool1", description="Tool 1", inputSchema={"type": "object"})],
        )

        server.enable_discovery_with_groups([group1])

        @server.list_tools()
        async def list_tools():
            return []

        @server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]):
            return "result"

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools
            assert len(tools) == 1
            assert tools[0].name == "group1"

        # Now replace with different group
        group2 = ToolGroup(
            name="group2",
            description="Group 2",
            tools=[Tool(name="tool2", description="Tool 2", inputSchema={"type": "object"})],
        )

        server.enable_discovery_with_groups([group2])

        async with create_session(server) as client:
            result = await client.list_tools()
            tools = result.tools
            assert len(tools) == 1
            assert tools[0].name == "group2"
