"""Companion examples for src/mcp/shared/exceptions.py docstrings."""

from __future__ import annotations

from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.types import ElicitRequestURLParams


def UrlElicitationRequiredError_usage() -> None:
    # region UrlElicitationRequiredError_usage
    raise UrlElicitationRequiredError(
        [
            ElicitRequestURLParams(
                message="Authorization required for your files",
                url="https://example.com/oauth/authorize",
                elicitation_id="auth-001",
            )
        ]
    )
    # endregion UrlElicitationRequiredError_usage
