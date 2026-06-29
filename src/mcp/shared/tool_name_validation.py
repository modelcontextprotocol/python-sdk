"""Tool name validation per SEP-986: 1-128 characters from A-Z, a-z, 0-9, `_`, `-`, `.`.

See: https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-names
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TOOL_NAME_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

SEP_986_URL = "https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-names"


@dataclass
class ToolNameValidationResult:
    """Result of tool name validation."""

    is_valid: bool
    warnings: list[str] = field(default_factory=lambda: [])


def validate_tool_name(name: str) -> ToolNameValidationResult:
    """Validate a tool name against SEP-986; a valid name may still carry warnings."""
    warnings: list[str] = []

    if not name:
        return ToolNameValidationResult(
            is_valid=False,
            warnings=["Tool name cannot be empty"],
        )

    if len(name) > 128:
        return ToolNameValidationResult(
            is_valid=False,
            warnings=[f"Tool name exceeds maximum length of 128 characters (current: {len(name)})"],
        )

    if " " in name:
        warnings.append("Tool name contains spaces, which may cause parsing issues")

    if "," in name:
        warnings.append("Tool name contains commas, which may cause parsing issues")

    if name.startswith("-") or name.endswith("-"):
        warnings.append("Tool name starts or ends with a dash, which may cause parsing issues in some contexts")

    if name.startswith(".") or name.endswith("."):
        warnings.append("Tool name starts or ends with a dot, which may cause parsing issues in some contexts")

    if not TOOL_NAME_REGEX.match(name):
        # Collect invalid characters, unique and in order of first appearance
        invalid_chars: list[str] = []
        seen: set[str] = set()
        for char in name:
            if not re.match(r"[A-Za-z0-9._-]", char) and char not in seen:
                invalid_chars.append(char)
                seen.add(char)

        warnings.append(f"Tool name contains invalid characters: {', '.join(repr(c) for c in invalid_chars)}")
        warnings.append("Allowed characters are: A-Z, a-z, 0-9, underscore (_), dash (-), and dot (.)")

        return ToolNameValidationResult(is_valid=False, warnings=warnings)

    return ToolNameValidationResult(is_valid=True, warnings=warnings)


def issue_tool_name_warning(name: str, warnings: list[str]) -> None:
    """Log warnings for a non-conforming tool name."""
    if not warnings:
        return

    logger.warning(f'Tool name validation warning for "{name}":')
    for warning in warnings:
        logger.warning(f"  - {warning}")
    logger.warning("Tool registration will proceed, but this may cause compatibility issues.")
    logger.warning("Consider updating the tool name to conform to the MCP tool naming standard.")
    logger.warning(f"See SEP-986 ({SEP_986_URL}) for more details.")


def validate_and_warn_tool_name(name: str) -> bool:
    """Validate a tool name, log any warnings, and return whether it is valid."""
    result = validate_tool_name(name)
    issue_tool_name_warning(name, result.warnings)
    return result.is_valid
