"""Regression: tool input schemas omit pydantic auto-derived property titles (#3391)."""

from pydantic import Field

from mcp.server.mcpserver.tools.base import Tool


def test_tool_input_schema_omits_auto_derived_property_titles():
    def log_set(exercise_id: str, reps: int) -> str:
        """Log a set."""
        return "ok"

    tool = Tool.from_function(log_set)
    props = tool.parameters["properties"]
    assert "title" not in props["exercise_id"]
    assert "title" not in props["reps"]
    assert props["exercise_id"]["type"] == "string"
    assert props["reps"]["type"] == "integer"


def test_tool_input_schema_keeps_explicit_field_title():
    def greet(name: str = Field(title="Preferred Name")) -> str:
        """Greet someone."""
        return f"hi {name}"

    tool = Tool.from_function(greet)
    props = tool.parameters["properties"]
    assert props["name"]["title"] == "Preferred Name"
