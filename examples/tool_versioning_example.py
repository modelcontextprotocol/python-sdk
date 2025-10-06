#!/usr/bin/env python3
"""
Example demonstrating tool versioning functionality in MCP.

This example shows how to:
1. Create tools with different versions
2. Use version constraints in tool calls
3. Handle version conflicts and errors
"""

import asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import UNSATISFIED_TOOL_VERSION


def create_versioned_server():
    """Create a server with multiple versions of tools."""
    server = FastMCP("versioned-tools-server")
    
    # Weather tool versions
    @server.tool(version="1.0.0")
    def get_weather_v1(location: str) -> str:
        """Get basic weather information (v1.0.0)."""
        return f"Weather in {location}: Sunny, 72°F (Basic API v1.0.0)"
    
    @server.tool(version="1.1.0")
    def get_weather_v1_1(location: str) -> str:
        """Get weather with humidity (v1.1.0)."""
        return f"Weather in {location}: Partly cloudy, 75°F, Humidity: 65% (Enhanced API v1.1.0)"
    
    @server.tool(version="2.0.0")
    def get_weather_v2(location: str) -> str:
        """Get detailed weather with forecast (v2.0.0)."""
        return f"Weather in {location}: Clear skies, 78°F, Humidity: 60%, Forecast: Sunny tomorrow (Advanced API v2.0.0)"
    
    # Calculator tool versions
    @server.tool(version="1.0.0")
    def calculate_v1(expression: str) -> float:
        """Basic calculator (v1.0.0)."""
        try:
            return eval(expression)
        except Exception as e:
            raise ValueError(f"Invalid expression: {e}")
    
    @server.tool(version="1.1.0")
    def calculate_v1_1(expression: str) -> dict:
        """Calculator with detailed output (v1.1.0)."""
        try:
            result = eval(expression)
            return {
                "result": result,
                "expression": expression,
                "type": type(result).__name__
            }
        except Exception as e:
            raise ValueError(f"Invalid expression: {e}")
    
    return server


async def demonstrate_versioning():
    """Demonstrate various versioning scenarios."""
    print("🚀 Tool Versioning Demonstration\n")
    
    server = create_versioned_server()
    
    # 1. List available tools and their versions
    print("1. Available Tools:")
    tools = server._tool_manager.list_tools()
    for tool in tools:
        print(f"   - {tool.name} (version: {tool.version})")
    print()
    
    # 2. Show available versions for each tool
    print("2. Available Versions:")
    for tool_name in ["get_weather_v1", "calculate_v1"]:
        versions = server._tool_manager.get_available_versions(tool_name)
        print(f"   - {tool_name}: {versions}")
    print()
    
    # 3. Demonstrate tool calls without version requirements (uses latest)
    print("3. Tool Calls Without Version Requirements (Latest Version):")
    try:
        result = await server.call_tool("get_weather_v1", {"location": "New York"})
        print(f"   Weather result: {result}")
        
        result = await server.call_tool("calculate_v1", {"expression": "2 + 3 * 4"})
        print(f"   Calculator result: {result}")
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # 4. Demonstrate tool calls with version requirements
    print("4. Tool Calls With Version Requirements:")
    try:
        # Use caret constraint (^1.0.0) - allows non-breaking updates
        result = await server.call_tool(
            "get_weather_v1", 
            {"location": "San Francisco"},
            tool_requirements={"get_weather_v1": "^1.0.0"}
        )
        print(f"   Weather with ^1.0.0: {result}")
        
        # Use tilde constraint (~1.0.0) - allows only patch updates
        result = await server.call_tool(
            "calculate_v1",
            {"expression": "10 / 2"},
            tool_requirements={"calculate_v1": "~1.0.0"}
        )
        print(f"   Calculator with ~1.0.0: {result}")
        
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # 5. Demonstrate version conflict handling
    print("5. Version Conflict Handling:")
    try:
        # Try to use a version that doesn't exist
        result = await server.call_tool(
            "get_weather_v1",
            {"location": "Chicago"},
            tool_requirements={"get_weather_v1": "^3.0.0"}  # No v3.x exists
        )
        print(f"   Unexpected success: {result}")
    except ToolError as e:
        if hasattr(e, 'code') and e.code == UNSATISFIED_TOOL_VERSION:
            print(f"   ✓ Correctly caught version conflict: {e}")
        else:
            print(f"   Unexpected error: {e}")
    except Exception as e:
        print(f"   Unexpected error: {e}")
    print()
    
    # 6. Demonstrate exact version specification
    print("6. Exact Version Specification:")
    try:
        result = await server.call_tool(
            "get_weather_v1",
            {"location": "Boston"},
            tool_requirements={"get_weather_v1": "1.0.0"}  # Exact version
        )
        print(f"   Weather with exact 1.0.0: {result}")
        
        result = await server.call_tool(
            "calculate_v1",
            {"expression": "5 ** 2"},
            tool_requirements={"calculate_v1": "1.1.0"}  # Exact version
        )
        print(f"   Calculator with exact 1.1.0: {result}")
        
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    print("✅ Versioning demonstration completed!")


async def main():
    """Run the demonstration."""
    await demonstrate_versioning()


if __name__ == "__main__":
    asyncio.run(main())