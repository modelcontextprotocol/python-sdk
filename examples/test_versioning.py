#!/usr/bin/env python3
"""
Test script for tool versioning functionality.

This script demonstrates the new tool versioning features implemented according to SEP-1575.
"""

import asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.versioning import (
    parse_version,
    compare_versions,
    satisfies_constraint,
    find_best_version,
    validate_tool_requirements,
    VersionConstraintError,
)


# Test version parsing and comparison
def test_version_parsing():
    """Test version parsing functionality."""
    print("Testing version parsing...")
    
    # Test valid versions
    assert parse_version("1.2.3") == (1, 2, 3, None)
    assert parse_version("2.0.0-alpha.1") == (2, 0, 0, "alpha.1")
    assert parse_version("0.1.0-beta") == (0, 1, 0, "beta")
    
    # Test version comparison
    assert compare_versions("1.2.3", "1.2.4") == -1
    assert compare_versions("2.0.0", "1.9.9") == 1
    assert compare_versions("1.2.3", "1.2.3") == 0
    assert compare_versions("1.2.3", "1.2.3-alpha") == 1  # Stable > prerelease
    
    print("✓ Version parsing tests passed")


def test_constraint_satisfaction():
    """Test constraint satisfaction functionality."""
    print("Testing constraint satisfaction...")
    
    # Test exact version
    assert satisfies_constraint("1.2.3", "1.2.3") == True
    assert satisfies_constraint("1.2.4", "1.2.3") == False
    
    # Test caret (^) - allows non-breaking updates
    assert satisfies_constraint("1.2.3", "^1.2.3") == True
    assert satisfies_constraint("1.3.0", "^1.2.3") == True
    assert satisfies_constraint("2.0.0", "^1.2.3") == False
    
    # Test tilde (~) - allows patch-level updates
    assert satisfies_constraint("1.2.3", "~1.2.3") == True
    assert satisfies_constraint("1.2.4", "~1.2.3") == True
    assert satisfies_constraint("1.3.0", "~1.2.3") == False
    
    # Test comparison operators
    assert satisfies_constraint("1.2.3", ">=1.2.0") == True
    assert satisfies_constraint("1.1.9", ">=1.2.0") == False
    assert satisfies_constraint("1.2.3", "<1.3.0") == True
    assert satisfies_constraint("1.3.0", "<1.3.0") == False
    
    print("✓ Constraint satisfaction tests passed")


def test_version_selection():
    """Test best version selection."""
    print("Testing version selection...")
    
    available_versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0-alpha.1", "2.0.0"]
    
    # Test caret constraint
    best = find_best_version(available_versions, "^1.0.0")
    assert best == "1.2.0"  # Latest in 1.x range
    
    # Test tilde constraint
    best = find_best_version(available_versions, "~1.1.0")
    assert best == "1.1.0"  # Exact match for patch level
    
    # Test exact version
    best = find_best_version(available_versions, "2.0.0")
    assert best == "2.0.0"
    
    # Test no match
    best = find_best_version(available_versions, "^3.0.0")
    assert best is None
    
    print("✓ Version selection tests passed")


def test_tool_requirements_validation():
    """Test tool requirements validation."""
    print("Testing tool requirements validation...")
    
    available_tools = {
        "weather": ["1.0.0", "1.1.0", "2.0.0"],
        "calculator": ["1.0.0", "1.0.1", "1.1.0"],
    }
    
    # Test valid requirements
    requirements = {
        "weather": "^1.0.0",
        "calculator": "~1.0.0"
    }
    
    selected = validate_tool_requirements(requirements, available_tools)
    assert selected["weather"] == "1.1.0"  # Latest in 1.x range
    assert selected["calculator"] == "1.0.1"  # Latest patch in 1.0.x range
    
    # Test unsatisfied requirement
    requirements = {
        "weather": "^3.0.0"
    }
    
    try:
        validate_tool_requirements(requirements, available_tools)
        assert False, "Should have raised VersionConstraintError"
    except VersionConstraintError:
        pass  # Expected
    
    print("✓ Tool requirements validation tests passed")


# Create a simple FastMCP server with versioned tools
def create_test_server():
    """Create a test server with versioned tools."""
    server = FastMCP("test-server")
    
    def get_weather_v1(location: str) -> str:
        """Get weather for a location (v1)."""
        return f"Weather in {location}: Sunny, 72°F (v1.0.0)"
    
    def get_weather_v1_1(location: str) -> str:
        """Get weather for a location (v1.1)."""
        return f"Weather in {location}: Partly cloudy, 75°F (v1.1.0)"
    
    def get_weather_v2(location: str) -> str:
        """Get weather for a location (v2)."""
        return f"Weather in {location}: Clear skies, 78°F (v2.0.0)"
    
    def calculate_v1(expression: str) -> float:
        """Calculate a simple expression (v1)."""
        return eval(expression)  # Simple implementation for demo
    
    server.add_tool(get_weather_v1, version="1.0.0")
    server.add_tool(get_weather_v1_1, version="1.1.0")
    server.add_tool(get_weather_v2, version="2.0.0")
    server.add_tool(calculate_v1, version="1.0.0")
    
    return server


async def test_server_versioning():
    """Test server versioning functionality."""
    print("Testing server versioning...")
    
    server = create_test_server()
    
    # Test listing tools (should show latest versions)
    tools = server._tool_manager.list_tools()
    tool_names = [t.name for t in tools]
    print(f"Available tools: {tool_names}")
    assert "get_weather_v1" in tool_names
    assert "calculate_v1" in tool_names
    
    # Test getting specific version
    weather_v1 = server._tool_manager.get_tool("get_weather_v1", "1.0.0")
    assert weather_v1 is not None
    assert weather_v1.version == "1.0.0"
    
    # Test getting latest version
    weather_latest = server._tool_manager.get_tool("get_weather_v1")
    assert weather_latest is not None
    assert weather_latest.version == "1.0.0"  # Only one version for this tool
    
    # Test available versions
    versions = server._tool_manager.get_available_versions("get_weather_v1")
    assert "1.0.0" in versions
    
    print("✓ Server versioning tests passed")


async def main():
    """Run all tests."""
    print("Running tool versioning tests...\n")
    
    test_version_parsing()
    print()
    
    test_constraint_satisfaction()
    print()
    
    test_version_selection()
    print()
    
    test_tool_requirements_validation()
    print()
    
    await test_server_versioning()
    print()
    
    print("🎉 All tests passed! Tool versioning implementation is working correctly.")


if __name__ == "__main__":
    asyncio.run(main())