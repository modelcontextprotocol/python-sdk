"""Utilities for parsing function docstrings to extract summaries and parameter descriptions.

Supports Google, NumPy, and Sphinx (reST) docstring formats.
"""

from __future__ import annotations

import re


def parse_docstring(docstring: str | None) -> tuple[str, dict[str, str]]:
    """Parse a docstring and return (summary, param_descriptions).

    The summary is the text before the first recognized section header
    (Args, Parameters, :param, Returns, etc.). Parameter descriptions are
    extracted from whichever docstring style is detected.

    Supports Google, NumPy, and Sphinx (reST) docstring formats.

    Args:
        docstring: The raw docstring text, or None.

    Returns:
        A tuple of (summary_text, {param_name: description}).
        summary_text has leading/trailing whitespace stripped.
        param_name keys are the bare parameter names (no type info).
    """
    if not docstring:
        return ("", {})

    lines = docstring.expandtabs().splitlines()

    # Find where the summary ends by detecting the first section header.
    section_start = _find_section_start(lines)

    # Build the summary from lines before the section.
    summary = "\n".join(lines[:section_start]).strip()

    # Parse parameter descriptions from the section onward.
    param_descriptions: dict[str, str] = {}
    if section_start < len(lines):
        remaining = lines[section_start:]
        param_descriptions = (
            _try_parse_google_params(remaining)
            or _try_parse_sphinx_params(remaining)
            or _try_parse_numpy_params(remaining)
        )

    return (summary, param_descriptions)


# ---------------------------------------------------------------------------
# Section-start detection
# ---------------------------------------------------------------------------

# Google-style: "Args:", "Arguments:", "Parameters:", "Params:"
_GOOGLE_SECTION_RE = re.compile(
    r"^\s*(Args|Arguments|Parameters|Params|Returns?|Raises?|Yields?|Examples?|Notes?|References?|Attributes?|Todo)\s*:\s*$",
    re.IGNORECASE,
)

# NumPy-style: a word on its own line followed by a line of dashes
_NUMPY_SECTION_WORD_RE = re.compile(
    r"^\s*(Parameters|Returns?|Raises?|Yields?|Examples?|Notes?|References?|See Also|Attributes?|Methods)\s*$",
    re.IGNORECASE,
)
_NUMPY_DASHES_RE = re.compile(r"^\s*-{3,}\s*$")

# Sphinx-style: ":param ...", ":type ...", ":returns:", ":rtype:", ":raises:"
_SPHINX_DIRECTIVE_RE = re.compile(r"^\s*:(param|type|returns?|rtype|raises?)\s")


def _find_section_start(lines: list[str]) -> int:
    """Return the index of the first recognised section header, or len(lines)."""
    for i, line in enumerate(lines):
        if _GOOGLE_SECTION_RE.match(line):
            return i
        if _SPHINX_DIRECTIVE_RE.match(line):
            return i
        if _NUMPY_SECTION_WORD_RE.match(line) and i + 1 < len(lines) and _NUMPY_DASHES_RE.match(lines[i + 1]):
            return i
    return len(lines)


# ---------------------------------------------------------------------------
# Google-style parameter parsing
# ---------------------------------------------------------------------------

_GOOGLE_PARAM_SECTION_RE = re.compile(r"^\s*(Args|Arguments|Parameters|Params)\s*:\s*$", re.IGNORECASE)
_GOOGLE_OTHER_SECTION_RE = re.compile(
    r"^\s*(Returns?|Raises?|Yields?|Examples?|Notes?|References?|Attributes?|Todo)\s*:\s*$",
    re.IGNORECASE,
)
_GOOGLE_PARAM_LINE_RE = re.compile(r"^(\s+)(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)")


def _try_parse_google_params(lines: list[str]) -> dict[str, str]:
    """Parse Google-style parameter descriptions from *lines* (starting at a section header).

    Returns an empty dict if no Google-style parameters are found.
    """
    params: dict[str, str] = {}

    # Find the "Args:" (or similar) section.
    section_body_start: int | None = None
    for i, line in enumerate(lines):
        if _GOOGLE_PARAM_SECTION_RE.match(line):
            section_body_start = i + 1
            break

    if section_body_start is None:
        return params

    i = section_body_start
    base_indent: int | None = None

    while i < len(lines):
        line = lines[i]

        # Skip blank lines.
        if not line.strip():
            i += 1
            continue

        # Stop at another section header.
        if _GOOGLE_OTHER_SECTION_RE.match(line) or _GOOGLE_PARAM_SECTION_RE.match(line):
            break
        # Also stop at NumPy-style sections that happen to follow.
        if _NUMPY_SECTION_WORD_RE.match(line) and i + 1 < len(lines) and _NUMPY_DASHES_RE.match(lines[i + 1]):
            break

        m = _GOOGLE_PARAM_LINE_RE.match(line)
        if m:
            indent = len(m.group(1))
            if base_indent is None:
                base_indent = indent

            if indent == base_indent:
                param_name = m.group(2)
                desc_parts = [m.group(3).strip()] if m.group(3).strip() else []

                # Collect continuation lines (indented deeper than the param line).
                j = i + 1
                while j < len(lines):
                    cont = lines[j]
                    if not cont.strip():
                        j += 1
                        continue
                    cont_indent = len(cont) - len(cont.lstrip())
                    if cont_indent > base_indent:
                        desc_parts.append(cont.strip())
                        j += 1
                    else:
                        break
                params[param_name] = " ".join(desc_parts)
                i = j
                continue

        i += 1

    return params


# ---------------------------------------------------------------------------
# Sphinx (reST) parameter parsing
# ---------------------------------------------------------------------------

_SPHINX_PARAM_RE = re.compile(r"^\s*:param\s+(?:\w+\s+)?(\w+)\s*:\s*(.*)")


def _try_parse_sphinx_params(lines: list[str]) -> dict[str, str]:
    """Parse Sphinx-style parameter descriptions.

    Handles both ``:param name: desc`` and ``:param type name: desc`` forms.
    """
    params: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _SPHINX_PARAM_RE.match(line)
        if m:
            param_name = m.group(1)
            desc_parts = [m.group(2).strip()] if m.group(2).strip() else []
            param_indent = len(line) - len(line.lstrip())

            # Collect continuation lines.
            j = i + 1
            while j < len(lines):
                cont = lines[j]
                if not cont.strip():
                    j += 1
                    continue
                cont_indent = len(cont) - len(cont.lstrip())
                if cont.lstrip().startswith(":"):
                    break
                if cont_indent > param_indent:
                    desc_parts.append(cont.strip())
                    j += 1
                else:
                    break
            params[param_name] = " ".join(desc_parts)
            i = j
            continue
        i += 1

    return params


# ---------------------------------------------------------------------------
# NumPy-style parameter parsing
# ---------------------------------------------------------------------------

_NUMPY_PARAM_LINE_RE = re.compile(r"^(\s*)(\w+)\s*(?::\s*.*)?$")


def _try_parse_numpy_params(lines: list[str]) -> dict[str, str]:
    """Parse NumPy-style parameter descriptions.

    Format::

        Parameters
        ----------
        param_name : type
            Description of param.
    """
    params: dict[str, str] = {}

    # Find the "Parameters" section.
    section_body_start: int | None = None
    for i, line in enumerate(lines):
        if _NUMPY_SECTION_WORD_RE.match(line) and re.match(r"^\s*(Parameters)\s*$", line, re.IGNORECASE):
            if i + 1 < len(lines) and _NUMPY_DASHES_RE.match(lines[i + 1]):
                section_body_start = i + 2
                break

    if section_body_start is None:
        return params

    i = section_body_start
    while i < len(lines):
        line = lines[i]

        # Skip blank lines.
        if not line.strip():
            i += 1
            continue

        # Stop at another section (word followed by dashes).
        if _NUMPY_SECTION_WORD_RE.match(line) and i + 1 < len(lines) and _NUMPY_DASHES_RE.match(lines[i + 1]):
            break

        m = _NUMPY_PARAM_LINE_RE.match(line)
        if m:
            param_indent = len(m.group(1))
            param_name = m.group(2)

            # Description is on subsequent indented lines.
            desc_parts: list[str] = []
            j = i + 1
            while j < len(lines):
                desc_line = lines[j]
                if not desc_line.strip():
                    # Blank line might separate paragraphs within description.
                    # Look ahead to see if next non-blank is still indented.
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines):
                        next_indent = len(lines[k]) - len(lines[k].lstrip())
                        if next_indent > param_indent:
                            j += 1
                            continue
                    break

                desc_indent = len(desc_line) - len(desc_line.lstrip())
                if desc_indent > param_indent:
                    desc_parts.append(desc_line.strip())
                    j += 1
                else:
                    break

            if desc_parts:
                params[param_name] = " ".join(desc_parts)
            i = j
            continue

        i += 1

    return params
