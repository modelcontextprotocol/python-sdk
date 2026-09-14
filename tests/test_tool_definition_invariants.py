import re
import pytest

def validate_mcp_tool_name(name: str) -> bool:
    if not name or not (1 <= len(name) <= 64):
        return False
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

def test_valid_mcp_tool_names():
    assert validate_mcp_tool_name("query_database") is True
    assert validate_mcp_tool_name("fetch-api-v2") is True
    assert validate_mcp_tool_name("search123") is True

def test_invalid_mcp_tool_names():
    assert validate_mcp_tool_name("") is False
    assert validate_mcp_tool_name("tool with spaces") is False
    assert validate_mcp_tool_name("tool.with.dots") is False
