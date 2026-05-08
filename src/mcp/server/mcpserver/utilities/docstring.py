"""Lightweight Google-style docstring parser.

Extracts the summary line and per-parameter descriptions from a function
docstring so FastMCP can populate JSON schema descriptions for tool
parameters. Only Google-style docstrings are supported. NumPy and Sphinx
styles fall back to the summary-only behavior.
"""

import re
from textwrap import dedent

# Section headers we recognize. The summary ends at the first one of these,
# and the Args section ends when any header other than itself appears.
_SECTION_HEADERS = frozenset(
    [
        "args",
        "arguments",
        "params",
        "parameters",
        "returns",
        "return",
        "yields",
        "yield",
        "raises",
        "raise",
        "examples",
        "example",
        "notes",
        "note",
        "see also",
        "references",
        "attributes",
        "warnings",
        "warning",
        "todo",
    ]
)

_ARGS_HEADERS = frozenset(["args", "arguments", "params", "parameters"])


def _is_section_header(line: str) -> bool:
    """Return True if the stripped line is a recognized section header."""
    return line.strip().rstrip(":").lower() in _SECTION_HEADERS


def _parse_param_line(line: str) -> tuple[str, str] | None:
    """Try to parse a Google-style parameter line.

    Handles three forms::

        name: description
        name (type): description
        name (Annotated[list[int], Field(min_length=1)]): description

    The type annotation in parentheses may contain balanced nested parentheses,
    so we walk the string manually instead of using a simple regex.
    """
    match = re.match(r"^(\w+)\s*", line)
    if match is None:
        return None
    name = match.group(1)
    rest = line[match.end() :]

    # Optional type annotation in balanced parentheses
    if rest.startswith("("):
        depth = 0
        end_idx = -1
        for i, char in enumerate(rest):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
        if end_idx == -1:
            return None
        rest = rest[end_idx + 1 :]

    rest = rest.lstrip()
    if not rest.startswith(":"):
        return None
    description = rest[1:].strip()
    return name, description


def parse_docstring(docstring: str | None) -> tuple[str, dict[str, str]]:
    """Parse a Google-style docstring into a summary and parameter descriptions.

    Args:
        docstring: The raw function docstring, or None.

    Returns:
        A tuple of ``(summary, param_descriptions)`` where ``summary`` is the
        leading description text (everything before the first recognized
        section header) and ``param_descriptions`` maps parameter names to
        their description strings extracted from the Args section.
    """
    if not docstring:
        return "", {}

    text = dedent(docstring).strip()
    if not text:
        return "", {}

    lines = text.splitlines()
    summary_lines: list[str] = []
    param_descriptions: dict[str, str] = {}

    summary_done = False
    in_args_section = False
    current_param: str | None = None
    args_indent: int | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        # Detect Args/Parameters section start
        if not in_args_section and stripped.lower().rstrip(":") in _ARGS_HEADERS:
            in_args_section = True
            summary_done = True
            current_param = None
            args_indent = None
            continue

        if in_args_section:
            # Empty line: end the current parameter's continuation
            if not stripped:
                current_param = None
                continue

            # Any other section header ends the Args section permanently
            if _is_section_header(stripped):
                in_args_section = False
                current_param = None
                continue

            indent = len(line) - len(line.lstrip())

            # First non-empty line in Args sets the baseline indent
            if args_indent is None:
                args_indent = indent

            # A line at the args baseline indent starts a new parameter entry
            if indent <= args_indent:
                parsed = _parse_param_line(stripped)
                if parsed is not None:
                    name, desc = parsed
                    param_descriptions[name] = desc
                    current_param = name
                else:
                    current_param = None
            elif current_param is not None:
                # Continuation line for the current parameter
                existing = param_descriptions[current_param]
                joined = f"{existing} {stripped}" if existing else stripped
                param_descriptions[current_param] = joined
            continue

        # Outside Args section: collect summary lines until we hit any section
        if summary_done:
            continue
        if _is_section_header(stripped):
            summary_done = True
            continue
        summary_lines.append(stripped)

    # Trim trailing empty summary lines and collapse to a single paragraph
    while summary_lines and not summary_lines[-1]:
        summary_lines.pop()
    summary = " ".join(line for line in summary_lines if line).strip()

    return summary, param_descriptions
