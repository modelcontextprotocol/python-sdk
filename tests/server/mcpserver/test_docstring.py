"""Tests for the Google-style docstring parser."""

from mcp.server.mcpserver.utilities.docstring import parse_docstring


def test_none_docstring():
    summary, params = parse_docstring(None)
    assert summary == ""
    assert params == {}


def test_empty_docstring():
    summary, params = parse_docstring("")
    assert summary == ""
    assert params == {}


def test_whitespace_only_docstring():
    summary, params = parse_docstring("   \n  \n  ")
    assert summary == ""
    assert params == {}


def test_summary_only():
    summary, params = parse_docstring("Adds two numbers.")
    assert summary == "Adds two numbers."
    assert params == {}


def test_multi_line_summary():
    docstring = """
    Adds two numbers
    and returns the result.
    """
    summary, params = parse_docstring(docstring)
    assert summary == "Adds two numbers and returns the result."
    assert params == {}


def test_google_style_with_types():
    docstring = """
    Adds two numbers and returns the result.

    Args:
        a (float): The first number.
        b (float): The second number.

    Returns:
        float: The sum of a and b.
    """
    summary, params = parse_docstring(docstring)
    assert summary == "Adds two numbers and returns the result."
    assert params == {"a": "The first number.", "b": "The second number."}


def test_google_style_without_types():
    docstring = """
    Greets a user.

    Args:
        name: The name of the user.
        greeting: The greeting message.
    """
    summary, params = parse_docstring(docstring)
    assert summary == "Greets a user."
    assert params == {"name": "The name of the user.", "greeting": "The greeting message."}


def test_multiline_param_description():
    docstring = """
    Does a thing.

    Args:
        config: A long configuration value
            that spans multiple lines
            with extra detail.
        other: Single line.
    """
    summary, params = parse_docstring(docstring)
    assert summary == "Does a thing."
    assert params["config"] == "A long configuration value that spans multiple lines with extra detail."
    assert params["other"] == "Single line."


def test_arguments_section_header_alias():
    docstring = """
    Tool function.

    Arguments:
        x: First arg.
        y: Second arg.
    """
    _, params = parse_docstring(docstring)
    assert params == {"x": "First arg.", "y": "Second arg."}


def test_parameters_section_header_alias():
    docstring = """
    Tool function.

    Parameters:
        x: First arg.
    """
    _, params = parse_docstring(docstring)
    assert params == {"x": "First arg."}


def test_section_after_args_terminates_parsing():
    docstring = """
    Reads a file.

    Args:
        path: Path to file.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    summary, params = parse_docstring(docstring)
    assert summary == "Reads a file."
    assert params == {"path": "Path to file."}


def test_empty_line_in_args_section_resets_continuation():
    docstring = """
    Function.

    Args:
        a: First param.

        b: Second param after blank line.
    """
    _, params = parse_docstring(docstring)
    assert params == {"a": "First param.", "b": "Second param after blank line."}


def test_summary_with_section_header_immediately():
    docstring = """Args:
        x: Just a param.
    """
    summary, params = parse_docstring(docstring)
    assert summary == ""
    assert params == {"x": "Just a param."}


def test_unrecognized_continuation_without_current_param():
    docstring = """
    Function.

    Args:
        not a param line
            indented continuation that should be ignored
        x: Real param.
    """
    _, params = parse_docstring(docstring)
    assert params == {"x": "Real param."}


def test_returns_section_only_no_args():
    docstring = """
    Computes a value.

    Returns:
        int: The computed value.
    """
    summary, params = parse_docstring(docstring)
    assert summary == "Computes a value."
    assert params == {}


def test_complex_type_annotation_in_param():
    docstring = """
    Function.

    Args:
        data (Annotated[list[int], Field(min_length=1)]): Input data.
    """
    _, params = parse_docstring(docstring)
    assert params == {"data": "Input data."}
