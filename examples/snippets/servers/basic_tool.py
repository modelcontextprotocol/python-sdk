from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Tool Example")


@mcp.tool(description="Add two numbers")
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mcp.tool(description="Get weather for a city")
def get_weather(city: str, unit: str = "celsius") -> str:
    """Get weather for a city."""
    # This would normally call a weather API
    return f"Weather in {city}: 22°{unit[0].upper()}"
