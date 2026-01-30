"""Test that parameter descriptions are properly exposed through list_tools"""

from typing import Annotated

import pytest
from pydantic import Field

from mcp.server.mcpserver import MCPServer


@pytest.mark.anyio
async def test_parameter_descriptions():
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def greet(
        name: str = Field(description="The name to greet"),
        title: str = Field(description="Optional title", default=""),
    ) -> str:  # pragma: no cover
        """A greeting tool"""
        return f"Hello {title} {name}"

    tools = await mcp.list_tools()
    assert len(tools) == 1
    tool = tools[0]

    # Check that parameter descriptions are present in the schema
    properties = tool.input_schema["properties"]
    assert "name" in properties
    assert properties["name"]["description"] == "The name to greet"
    assert "title" in properties
    assert properties["title"]["description"] == "Optional title"


@pytest.mark.anyio
async def test_docstring_parameter_descriptions_google():
    """Parameter descriptions from Google-style docstrings appear in the schema."""
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def add_numbers(a: float, b: float) -> float:  # pragma: no cover
        """Add two numbers together.

        Args:
            a: The first number to add.
            b: The second number to add.

        Returns:
            The sum of a and b.
        """
        return a + b

    tools = await mcp.list_tools()
    tool = tools[0]
    properties = tool.input_schema["properties"]
    assert properties["a"]["description"] == "The first number to add."
    assert properties["b"]["description"] == "The second number to add."
    # Tool description should be the summary, not the full docstring
    assert tool.description == "Add two numbers together."


@pytest.mark.anyio
async def test_docstring_parameter_descriptions_numpy():
    """Parameter descriptions from NumPy-style docstrings appear in the schema."""
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def multiply(x: float, y: float) -> float:  # pragma: no cover
        """Multiply two numbers.

        Parameters
        ----------
        x
            The first factor.
        y
            The second factor.
        """
        return x * y

    tools = await mcp.list_tools()
    tool = tools[0]
    properties = tool.input_schema["properties"]
    assert properties["x"]["description"] == "The first factor."
    assert properties["y"]["description"] == "The second factor."
    assert tool.description == "Multiply two numbers."


@pytest.mark.anyio
async def test_docstring_parameter_descriptions_sphinx():
    """Parameter descriptions from Sphinx-style docstrings appear in the schema."""
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def divide(numerator: float, denominator: float) -> float:  # pragma: no cover
        """Divide two numbers.

        :param numerator: The number to divide.
        :param denominator: The number to divide by.
        :returns: The quotient.
        """
        return numerator / denominator

    tools = await mcp.list_tools()
    tool = tools[0]
    properties = tool.input_schema["properties"]
    assert properties["numerator"]["description"] == "The number to divide."
    assert properties["denominator"]["description"] == "The number to divide by."
    assert tool.description == "Divide two numbers."


@pytest.mark.anyio
async def test_field_description_takes_precedence_over_docstring():
    """Field(description=...) should take precedence over docstring descriptions."""
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def process(
        name: str = Field(description="From Field annotation"),
        value: int = 0,
    ) -> str:  # pragma: no cover
        """Process data.

        Args:
            name: From docstring.
            value: The value to process.
        """
        return f"{name}: {value}"

    tools = await mcp.list_tools()
    tool = tools[0]
    properties = tool.input_schema["properties"]
    # Field annotation takes precedence
    assert properties["name"]["description"] == "From Field annotation"
    # Docstring description used as fallback
    assert properties["value"]["description"] == "The value to process."


@pytest.mark.anyio
async def test_annotated_field_description_takes_precedence():
    """Annotated[type, Field(description=...)] should take precedence over docstring."""
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def process(
        name: Annotated[str, Field(description="From Annotated Field")],
        value: int = 0,
    ) -> str:  # pragma: no cover
        """Process data.

        Args:
            name: From docstring.
            value: The value to process.
        """
        return f"{name}: {value}"

    tools = await mcp.list_tools()
    tool = tools[0]
    properties = tool.input_schema["properties"]
    # Annotated Field takes precedence
    assert properties["name"]["description"] == "From Annotated Field"
    # Docstring description used as fallback
    assert properties["value"]["description"] == "The value to process."


@pytest.mark.anyio
async def test_explicit_description_kwarg_takes_precedence():
    """Explicit description= kwarg to @mcp.tool() takes precedence over docstring summary."""
    mcp = MCPServer("Test Server")

    @mcp.tool(description="Explicit tool description")
    def my_tool(a: int) -> int:  # pragma: no cover
        """Docstring summary that should not be used.

        Args:
            a: The value.
        """
        return a

    tools = await mcp.list_tools()
    tool = tools[0]
    assert tool.description == "Explicit tool description"
    # But parameter descriptions from docstring should still work
    properties = tool.input_schema["properties"]
    assert properties["a"]["description"] == "The value."


@pytest.mark.anyio
async def test_no_docstring_no_descriptions():
    """Functions without docstrings should work as before."""
    mcp = MCPServer("Test Server")

    @mcp.tool()
    def no_doc(a: int) -> int:  # pragma: no cover
        return a

    tools = await mcp.list_tools()
    tool = tools[0]
    assert tool.description == ""
    properties = tool.input_schema["properties"]
    assert "description" not in properties["a"]
