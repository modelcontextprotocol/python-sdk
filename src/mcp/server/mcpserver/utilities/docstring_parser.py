"""Extract parameter descriptions from function docstrings.

Auto-detects Google, NumPy, and Sphinx styles.
"""

from __future__ import annotations

import re

_GOOGLE_SECTION_RE = re.compile(
    r"(?:Args|Arguments|Parameters)\s*:\s*\n"
    r"(.*?)"
    r"(?:\n\s*\n|\n\s*(?:Returns|Raises|Yields|Note|Example)|\Z)",
    re.DOTALL,
)
_GOOGLE_PARAM_RE = re.compile(r"^(\s+)(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)")

_NUMPY_SECTION_RE = re.compile(
    r"Parameters\s*\n\s*-{3,}\s*\n"
    r"(.*?)"
    r"(?:\n\s*(?:Returns|Raises|Yields|See Also|Note|Example)\s*\n\s*-{3,}|\Z)",
    re.DOTALL,
)
_NUMPY_PARAM_RE = re.compile(r"^\s*(\w+)\s*:\s*.*")

_SPHINX_PARAM_RE = re.compile(
    r":param\s+(?:\w+\s+)?(\w+)\s*:\s*(.+?)(?=\n\s*:|$)",
    re.DOTALL,
)

_NUMPY_SEPARATOR_RE = re.compile(r"-{3,}")


def parse_docstring_params(docstring: str | None) -> dict[str, str]:
    """Extract parameter name→description mapping from a docstring."""
    if not docstring:
        return {}

    if _NUMPY_SEPARATOR_RE.search(docstring):
        parsers = (_parse_numpy, _parse_google, _parse_sphinx)
    else:
        parsers = (_parse_google, _parse_sphinx, _parse_numpy)

    for parser in parsers:
        result = parser(docstring)
        if result:
            return result
    return {}


def _collect_indented_block(
    lines: list[str],
    param_re: re.Pattern[str],
    *,
    extract_desc_from_header: bool = True,
) -> dict[str, str]:
    """Walk *lines* and collect param→description pairs.

    A parameter header is any line matching *param_re* whose indent is
    ≤ the previous header's indent.  Everything indented deeper is treated
    as a continuation of the current description.
    """
    params: dict[str, str] = {}
    current_param: str | None = None
    desc_parts: list[str] = []
    header_indent = 999

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())
        m = param_re.match(line)

        if m and indent <= header_indent:
            if current_param is not None:
                params[current_param] = " ".join(desc_parts).strip()

            header_indent = indent
            current_param = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)

            if extract_desc_from_header and m.lastindex and m.lastindex >= 3:
                tail = m.group(3).strip()
                desc_parts = [tail] if tail else []
            else:
                desc_parts = []
        elif current_param is not None and indent > header_indent:
            desc_parts.append(stripped.strip())

    if current_param is not None:
        params[current_param] = " ".join(desc_parts).strip()
    return params


def _parse_google(docstring: str) -> dict[str, str]:
    match = _GOOGLE_SECTION_RE.search(docstring)
    if not match:
        return {}
    return _collect_indented_block(
        match.group(1).split("\n"),
        _GOOGLE_PARAM_RE,
        extract_desc_from_header=True,
    )


def _parse_numpy(docstring: str) -> dict[str, str]:
    match = _NUMPY_SECTION_RE.search(docstring)
    if not match:
        return {}
    return _collect_indented_block(
        match.group(1).split("\n"),
        _NUMPY_PARAM_RE,
        extract_desc_from_header=False,
    )


def _parse_sphinx(docstring: str) -> dict[str, str]:
    return {m.group(1): " ".join(m.group(2).split()).strip() for m in _SPHINX_PARAM_RE.finditer(docstring)}
