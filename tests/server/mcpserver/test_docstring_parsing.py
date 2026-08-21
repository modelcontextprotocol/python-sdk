# pyright: reportUnknownParameterType=false
# pyright: reportMissingParameterType=false
# pyright: reportUnknownArgumentType=false
"""Tests for docstring parsing and integration with func_metadata / Tool.from_function."""

from typing import Annotated

from pydantic import Field

from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.utilities.docstring_parsing import parse_docstring
from mcp.server.mcpserver.utilities.func_metadata import func_metadata

# ---------------------------------------------------------------------------
# Unit tests for parse_docstring
# ---------------------------------------------------------------------------


class TestParseDocstringGoogle:
    """Google-style docstring parsing."""

    def test_summary_and_params(self):
        docstring = """Do something useful.

        This is extra description.

        Args:
            x: The x value.
            y (int): The y value.
        """
        summary, params = parse_docstring(docstring)
        assert summary == "Do something useful.\n\nThis is extra description."
        assert params == {"x": "The x value.", "y": "The y value."}

    def test_multiline_param_description(self):
        docstring = """Summary.

        Args:
            x: A long description
                that spans multiple lines.
            y: Short.
        """
        summary, params = parse_docstring(docstring)
        assert summary == "Summary."
        assert params["x"] == "A long description that spans multiple lines."
        assert params["y"] == "Short."

    def test_params_stops_at_returns(self):
        docstring = """Summary.

        Args:
            x: The x value.

        Returns:
            Something.
        """
        summary, params = parse_docstring(docstring)
        assert summary == "Summary."
        assert params == {"x": "The x value."}

    def test_arguments_keyword(self):
        docstring = """Summary.

        Arguments:
            name: The name.
        """
        _, params = parse_docstring(docstring)
        assert params == {"name": "The name."}

    def test_parameters_keyword(self):
        docstring = """Summary.

        Parameters:
            name: The name.
        """
        _, params = parse_docstring(docstring)
        assert params == {"name": "The name."}


class TestParseDocstringNumPy:
    """NumPy-style docstring parsing."""

    def test_summary_and_params(self):
        docstring = """Do something useful.

        Parameters
        ----------
        x : int
            The x value.
        y : str
            The y value.
        """
        summary, params = parse_docstring(docstring)
        assert summary == "Do something useful."
        assert params == {"x": "The x value.", "y": "The y value."}

    def test_multiline_param_description(self):
        docstring = """Summary.

        Parameters
        ----------
        x : int
            A long description
            that spans multiple lines.
        y : str
            Short.
        """
        summary, params = parse_docstring(docstring)
        assert params["x"] == "A long description that spans multiple lines."
        assert params["y"] == "Short."

    def test_stops_at_returns_section(self):
        docstring = """Summary.

        Parameters
        ----------
        x : int
            The x value.

        Returns
        -------
        str
            Something.
        """
        summary, params = parse_docstring(docstring)
        assert summary == "Summary."
        assert params == {"x": "The x value."}


class TestParseDocstringSphinx:
    """Sphinx (reST) docstring parsing."""

    def test_summary_and_params(self):
        docstring = """Do something useful.

        :param x: The x value.
        :param y: The y value.
        """
        summary, params = parse_docstring(docstring)
        assert summary == "Do something useful."
        assert params == {"x": "The x value.", "y": "The y value."}

    def test_typed_param(self):
        docstring = """Summary.

        :param int x: The x value.
        :param str y: The y value.
        """
        _, params = parse_docstring(docstring)
        assert params == {"x": "The x value.", "y": "The y value."}

    def test_multiline_param_description(self):
        docstring = """Summary.

        :param x: A long description
            that spans multiple lines.
        :param y: Short.
        """
        _, params = parse_docstring(docstring)
        assert params["x"] == "A long description that spans multiple lines."
        assert params["y"] == "Short."

    def test_skips_type_directives(self):
        docstring = """Summary.

        :param x: The x value.
        :type x: int
        :param y: The y value.
        """
        _, params = parse_docstring(docstring)
        assert params == {"x": "The x value.", "y": "The y value."}


class TestParseDocstringEdgeCases:
    """Edge cases for parse_docstring."""

    def test_none_docstring(self):
        summary, params = parse_docstring(None)
        assert summary == ""
        assert params == {}

    def test_empty_docstring(self):
        summary, params = parse_docstring("")
        assert summary == ""
        assert params == {}

    def test_summary_only(self):
        summary, params = parse_docstring("Just a summary.")
        assert summary == "Just a summary."
        assert params == {}

    def test_multiline_summary_only(self):
        summary, params = parse_docstring("First line.\n\nSecond paragraph.")
        assert summary == "First line.\n\nSecond paragraph."
        assert params == {}


# ---------------------------------------------------------------------------
# Integration: func_metadata with docstring_param_descriptions
# ---------------------------------------------------------------------------


class TestFuncMetadataDocstringDescriptions:
    """Test that docstring param descriptions are injected into the Pydantic model."""

    def test_descriptions_injected(self):
        def my_func(x: int, y: str) -> str:
            return f"{x}{y}"

        meta = func_metadata(
            my_func,
            docstring_param_descriptions={"x": "The x value.", "y": "The y value."},
        )
        schema = meta.arg_model.model_json_schema()
        assert schema["properties"]["x"]["description"] == "The x value."
        assert schema["properties"]["y"]["description"] == "The y value."

    def test_explicit_field_description_takes_precedence(self):
        def my_func(x: Annotated[int, Field(description="Explicit desc")], y: str) -> str:
            return f"{x}{y}"

        meta = func_metadata(
            my_func,
            docstring_param_descriptions={"x": "Docstring desc.", "y": "The y value."},
        )
        schema = meta.arg_model.model_json_schema()
        assert schema["properties"]["x"]["description"] == "Explicit desc"
        assert schema["properties"]["y"]["description"] == "The y value."

    def test_explicit_default_field_description_takes_precedence(self):
        def my_func(x: int = Field(1, description="Default field desc"), y: str = "hi") -> str:  # type: ignore[assignment]
            return f"{x}{y}"

        meta = func_metadata(
            my_func,
            docstring_param_descriptions={"x": "Docstring desc.", "y": "The y value."},
        )
        schema = meta.arg_model.model_json_schema()
        assert schema["properties"]["x"]["description"] == "Default field desc"
        assert schema["properties"]["y"]["description"] == "The y value."

    def test_no_docstring_descriptions(self):
        def my_func(x: int) -> str:
            return str(x)

        meta = func_metadata(my_func, docstring_param_descriptions=None)
        schema = meta.arg_model.model_json_schema()
        assert "description" not in schema["properties"]["x"]

    def test_partial_docstring_descriptions(self):
        def my_func(x: int, y: str) -> str:
            return f"{x}{y}"

        meta = func_metadata(
            my_func,
            docstring_param_descriptions={"x": "Only x described."},
        )
        schema = meta.arg_model.model_json_schema()
        assert schema["properties"]["x"]["description"] == "Only x described."
        assert "description" not in schema["properties"]["y"]


# ---------------------------------------------------------------------------
# Integration: Tool.from_function end-to-end
# ---------------------------------------------------------------------------


class TestToolFromFunctionDocstring:
    """Test that Tool.from_function uses the docstring summary and injects param descriptions."""

    def test_google_style(self):
        def my_tool(x: int, y: str) -> str:
            """Do something useful.

            Args:
                x: The x value.
                y: The y value.

            Returns:
                A result string.
            """
            return f"{x}{y}"

        tool = Tool.from_function(my_tool)
        assert tool.description == "Do something useful."
        assert tool.parameters["properties"]["x"]["description"] == "The x value."
        assert tool.parameters["properties"]["y"]["description"] == "The y value."

    def test_numpy_style(self):
        def my_tool(x: int, y: str) -> str:
            """Do something useful.

            Parameters
            ----------
            x : int
                The x value.
            y : str
                The y value.

            Returns
            -------
            str
                A result string.
            """
            return f"{x}{y}"

        tool = Tool.from_function(my_tool)
        assert tool.description == "Do something useful."
        assert tool.parameters["properties"]["x"]["description"] == "The x value."
        assert tool.parameters["properties"]["y"]["description"] == "The y value."

    def test_sphinx_style(self):
        def my_tool(x: int, y: str) -> str:
            """Do something useful.

            :param x: The x value.
            :param y: The y value.
            :returns: A result string.
            """
            return f"{x}{y}"

        tool = Tool.from_function(my_tool)
        assert tool.description == "Do something useful."
        assert tool.parameters["properties"]["x"]["description"] == "The x value."
        assert tool.parameters["properties"]["y"]["description"] == "The y value."

    def test_no_docstring(self):
        def my_tool(x: int) -> str:
            return str(x)

        tool = Tool.from_function(my_tool)
        assert tool.description == ""
        assert "description" not in tool.parameters["properties"]["x"]

    def test_summary_only_docstring(self):
        def my_tool(x: int) -> str:
            """Just a summary."""
            return str(x)

        tool = Tool.from_function(my_tool)
        assert tool.description == "Just a summary."
        assert "description" not in tool.parameters["properties"]["x"]

    def test_explicit_description_overrides_docstring(self):
        def my_tool(x: int) -> str:
            """Docstring summary.

            Args:
                x: From docstring.
            """
            return str(x)

        tool = Tool.from_function(my_tool, description="Explicit description")
        assert tool.description == "Explicit description"
        # When an explicit description is provided, docstring param parsing is skipped.
        assert "description" not in tool.parameters["properties"]["x"]

    def test_explicit_field_description_wins_over_docstring(self):
        def my_tool(x: Annotated[int, Field(description="From Field")], y: str) -> str:
            """Summary.

            Args:
                x: From docstring.
                y: Y from docstring.
            """
            return f"{x}{y}"

        tool = Tool.from_function(my_tool)
        assert tool.description == "Summary."
        assert tool.parameters["properties"]["x"]["description"] == "From Field"
        assert tool.parameters["properties"]["y"]["description"] == "Y from docstring."

    def test_multiline_summary_before_args(self):
        def my_tool(x: int) -> str:
            """First line of summary.

            More details about the tool.

            Args:
                x: The x value.
            """
            return str(x)

        tool = Tool.from_function(my_tool)
        assert tool.description == "First line of summary.\n\nMore details about the tool."
        assert tool.parameters["properties"]["x"]["description"] == "The x value."
