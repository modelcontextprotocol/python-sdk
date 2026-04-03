"""Tests for docstring parameter description parsing."""

from typing import Annotated

import pytest
from pydantic import Field

from mcp.server.mcpserver.utilities.docstring_parser import parse_docstring_params
from mcp.server.mcpserver.utilities.func_metadata import func_metadata


class TestGoogleStyle:
    def test_basic(self):
        doc = """Do something.

        Args:
            name: The name of the thing.
            count: How many times.
        """
        assert parse_docstring_params(doc) == {
            "name": "The name of the thing.",
            "count": "How many times.",
        }

    def test_with_type_annotations(self):
        doc = """Do something.

        Args:
            name (str): The name of the thing.
            count (int): How many times.
        """
        assert parse_docstring_params(doc) == {
            "name": "The name of the thing.",
            "count": "How many times.",
        }

    def test_multiline_description(self):
        doc = """Do something.

        Args:
            name: The name of the thing.
                This is a longer description
                that spans multiple lines.
            count: How many times.
        """
        result = parse_docstring_params(doc)
        assert "longer description" in result["name"]
        assert result["count"] == "How many times."

    @pytest.mark.parametrize("keyword", ["Args", "Arguments", "Parameters"])
    def test_section_keywords(self, keyword: str) -> None:
        doc = f"""Do something.

        {keyword}:
            name: The name.
        """
        assert parse_docstring_params(doc) == {"name": "The name."}

    def test_stops_at_returns(self):
        doc = """Do something.

        Args:
            name: The name.

        Returns:
            The result.
        """
        assert parse_docstring_params(doc) == {"name": "The name."}


class TestNumpyStyle:
    def test_basic(self):
        doc = """Do something.

        Parameters
        ----------
        name : str
            The name of the thing.
        count : int
            How many times.
        """
        assert parse_docstring_params(doc) == {
            "name": "The name of the thing.",
            "count": "How many times.",
        }

    def test_multiline(self):
        doc = """Do something.

        Parameters
        ----------
        name : str
            The name of the thing.
            More details here.
        """
        assert "More details" in parse_docstring_params(doc)["name"]


class TestSphinxStyle:
    def test_basic(self):
        doc = """Do something.

        :param name: The name of the thing.
        :param count: How many times.
        """
        assert parse_docstring_params(doc) == {
            "name": "The name of the thing.",
            "count": "How many times.",
        }

    def test_with_type(self):
        doc = """Do something.

        :param str name: The name of the thing.
        """
        assert parse_docstring_params(doc) == {"name": "The name of the thing."}


class TestEdgeCases:
    @pytest.mark.parametrize("doc", [None, "", "Just a description."])
    def test_returns_empty(self, doc: str | None) -> None:
        assert parse_docstring_params(doc) == {}

    def test_google_section_with_no_valid_params(self):
        doc = """Do something.

        Args:
            not a valid param line at all
            another invalid line
        """
        assert parse_docstring_params(doc) == {}

    def test_numpy_section_with_no_valid_params(self):
        doc = """Do something.

        Parameters
        ----------
        not a valid line
            just some text
        """
        assert parse_docstring_params(doc) == {}


class TestFuncMetadataIntegration:
    def test_descriptions_appear_in_schema(self):
        def my_tool(name: str, count: int = 5) -> str:
            """A tool.

            Args:
                name: The name to process.
                count: Number of repetitions.
            """
            return name * count  # pragma: no cover

        schema = func_metadata(my_tool).arg_model.model_json_schema()
        assert schema["properties"]["name"]["description"] == "The name to process."
        assert schema["properties"]["count"]["description"] == "Number of repetitions."

    def test_explicit_field_takes_precedence(self):
        def my_tool(
            name: Annotated[str, Field(description="Explicit")],
            count: int = 5,
        ) -> str:
            """A tool.

            Args:
                name: Should be ignored.
                count: From docstring.
            """
            return name * count  # pragma: no cover

        schema = func_metadata(my_tool).arg_model.model_json_schema()
        assert schema["properties"]["name"]["description"] == "Explicit"
        assert schema["properties"]["count"]["description"] == "From docstring."

    def test_annotated_without_field_uses_docstring(self):
        def my_tool(
            name: Annotated[str, "just a string annotation"],
            count: int = 5,
        ) -> str:
            """A tool.

            Args:
                name: From docstring.
                count: Also docstring.
            """
            return name * count  # pragma: no cover

        schema = func_metadata(my_tool).arg_model.model_json_schema()
        assert schema["properties"]["name"]["description"] == "From docstring."

    def test_no_docstring(self):
        def my_tool(name: str) -> str:
            return name  # pragma: no cover

        schema = func_metadata(my_tool).arg_model.model_json_schema()
        assert "name" in schema["properties"]
