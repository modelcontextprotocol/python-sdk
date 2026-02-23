"""Example showing how to handle and return errors from tools."""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

mcp = FastMCP("Tool Error Handling Example")


# Option 1: Raise ToolError for expected error conditions.
# The error message is returned to the client with isError=True.
@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide two numbers."""
    if b == 0:
        raise ToolError("Cannot divide by zero")
    return a / b


# Option 2: Unhandled exceptions are automatically caught and
# converted to error responses with isError=True.
@mcp.tool()
def read_config(path: str) -> str:
    """Read a configuration file."""
    # If this raises FileNotFoundError, the client receives an
    # error response like "Error executing tool read_config: ..."
    with open(path) as f:
        return f.read()


# Option 3: Return CallToolResult directly for full control
# over error responses, including custom content.
@mcp.tool()
def validate_input(data: str) -> CallToolResult:
    """Validate input data."""
    errors: list[str] = []
    if len(data) < 3:
        errors.append("Input must be at least 3 characters")
    if not data.isascii():
        errors.append("Input must be ASCII only")

    if errors:
        return CallToolResult(
            content=[TextContent(type="text", text="\n".join(errors))],
            isError=True,
        )
    return CallToolResult(
        content=[TextContent(type="text", text="Validation passed")],
    )
