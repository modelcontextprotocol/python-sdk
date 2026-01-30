"""Tests for docstring parsing utilities."""

from mcp.server.mcpserver.utilities.docstring_utils import parse_docstring


def test_google_style_docstring():
    def add_numbers(a: float, b: float) -> float:
        """Adds two numbers and returns the result.

        Args:
            a: The first number.
            b: The second number.

        Returns:
            The sum of a and b.
        """
        return a + b

    summary, params = parse_docstring(add_numbers)
    assert summary == "Adds two numbers and returns the result."
    assert params == {"a": "The first number.", "b": "The second number."}


def test_numpy_style_docstring():
    def multiply(x: float, y: float) -> float:
        """Multiply two numbers.

        Parameters
        ----------
        x
            The first factor.
        y
            The second factor.

        Returns
        -------
        float
            The product of x and y.
        """
        return x * y

    summary, params = parse_docstring(multiply)
    assert summary == "Multiply two numbers."
    assert params == {"x": "The first factor.", "y": "The second factor."}


def test_sphinx_style_docstring():
    def divide(numerator: float, denominator: float) -> float:
        """Divide two numbers.

        :param numerator: The number to divide.
        :param denominator: The number to divide by.
        :returns: The quotient.
        """
        return numerator / denominator

    summary, params = parse_docstring(divide)
    assert summary == "Divide two numbers."
    assert params == {
        "numerator": "The number to divide.",
        "denominator": "The number to divide by.",
    }


def test_no_docstring():
    def no_doc(a: int) -> int:
        return a

    summary, params = parse_docstring(no_doc)
    assert summary is None
    assert params == {}


def test_summary_only_docstring():
    def simple(a: int) -> int:
        """A simple function."""
        return a

    summary, params = parse_docstring(simple)
    assert summary == "A simple function."
    assert params == {}


def test_multiline_summary():
    def multi(a: int) -> int:
        """This is a longer description
        that spans multiple lines.

        Args:
            a: An integer value.
        """
        return a

    summary, params = parse_docstring(multi)
    assert "longer description" in summary
    assert params == {"a": "An integer value."}


def test_empty_docstring():
    def empty_doc(a: int) -> int:
        """"""
        return a

    summary, params = parse_docstring(empty_doc)
    # Empty docstring should return None summary
    assert summary is None
    assert params == {}


def test_params_with_types_in_docstring():
    """Google-style docstrings sometimes include types in the param descriptions."""

    def typed_params(a: float, b: float) -> float:
        """Add numbers.

        Args:
            a (float): The first number.
            b (float): The second number.
        """
        return a + b

    summary, params = parse_docstring(typed_params)
    assert summary == "Add numbers."
    assert "first number" in params["a"]
    assert "second number" in params["b"]
