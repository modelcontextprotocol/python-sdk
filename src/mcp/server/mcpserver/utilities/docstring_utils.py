"""Utilities for parsing function docstrings to extract descriptions and parameter info.

Supports Google, NumPy, and Sphinx docstring formats with automatic detection.
Adapted from pydantic-ai's _griffe.py implementation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, Iterator, Literal

from griffe import Docstring, DocstringSectionKind

try:
    from griffe import GoogleOptions

    _GOOGLE_PARSER_OPTIONS = GoogleOptions(returns_named_value=False, returns_multiple_items=False)
except ImportError:
    _GOOGLE_PARSER_OPTIONS = None

DocstringStyle = Literal["google", "numpy", "sphinx"]


def parse_docstring(
    func: Callable[..., Any],
) -> tuple[str | None, dict[str, str]]:
    """Extract the function summary and parameter descriptions from a docstring.

    Automatically infers the docstring format (Google, NumPy, or Sphinx).

    Returns:
        A tuple of (summary, param_descriptions) where:
        - summary: The main description text (first section), or None if no docstring
        - param_descriptions: Dict mapping parameter names to their descriptions
    """
    doc = func.__doc__
    if doc is None:
        return None, {}

    docstring_style = _infer_docstring_style(doc)
    parser_options = _GOOGLE_PARSER_OPTIONS if docstring_style == "google" else None
    docstring = Docstring(
        doc,
        lineno=1,
        parser=docstring_style,
        parser_options=parser_options,
    )
    with _disable_griffe_logging():
        sections = docstring.parse()

    params: dict[str, str] = {}
    if parameters := next(
        (s for s in sections if s.kind == DocstringSectionKind.parameters), None
    ):
        params = {p.name: p.description for p in parameters.value if p.description}

    summary: str | None = None
    if main := next(
        (s for s in sections if s.kind == DocstringSectionKind.text), None
    ):
        summary = main.value.strip() if main.value else None

    return summary, params


def _infer_docstring_style(doc: str) -> DocstringStyle:
    """Infer the docstring style from its content."""
    for pattern, replacements, style in _DOCSTRING_STYLE_PATTERNS:
        matches = (
            re.search(pattern.format(replacement), doc, re.IGNORECASE | re.MULTILINE)
            for replacement in replacements
        )
        if any(matches):
            return style
    return "google"


# Pattern matching for docstring style detection.
# See https://github.com/mkdocstrings/griffe/issues/329#issuecomment-2425017804
_DOCSTRING_STYLE_PATTERNS: list[tuple[str, list[str], DocstringStyle]] = [
    (
        r"\n[ \t]*:{0}([ \t]+\w+)*:([ \t]+.+)?\n",
        [
            "param",
            "parameter",
            "arg",
            "argument",
            "type",
            "returns",
            "return",
            "rtype",
            "raises",
            "raise",
        ],
        "sphinx",
    ),
    (
        r"\n[ \t]*{0}:([ \t]+.+)?\n[ \t]+.+",
        [
            "args",
            "arguments",
            "params",
            "parameters",
            "raises",
            "returns",
            "yields",
            "examples",
            "attributes",
        ],
        "google",
    ),
    (
        r"\n[ \t]*{0}\n[ \t]*---+\n",
        [
            "parameters",
            "returns",
            "yields",
            "raises",
            "attributes",
        ],
        "numpy",
    ),
]


@contextmanager
def _disable_griffe_logging() -> Iterator[None]:
    """Temporarily suppress griffe logging to avoid noisy warnings."""
    old_level = logging.root.getEffectiveLevel()
    logging.root.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logging.root.setLevel(old_level)
