"""Tests for the RequestContext.experimental (Experimental class) task validation helpers."""

import pytest

from mcp.shared.context import Experimental
from mcp.shared.exceptions import McpError
from mcp.types import (
    METHOD_NOT_FOUND,
    ClientCapabilities,
    ClientTasksCapability,
    TaskMetadata,
    Tool,
    ToolExecution,
)

# --- Experimental.is_task ---


def test_is_task_true_when_metadata_present() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    assert exp.is_task is True


def test_is_task_false_when_no_metadata() -> None:
    exp = Experimental(task_metadata=None)
    assert exp.is_task is False


# --- Experimental.client_supports_tasks ---


def test_client_supports_tasks_true() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities(tasks=ClientTasksCapability()))
    assert exp.client_supports_tasks is True


def test_client_supports_tasks_false_no_tasks() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.client_supports_tasks is False


def test_client_supports_tasks_false_no_capabilities() -> None:
    exp = Experimental(_client_capabilities=None)
    assert exp.client_supports_tasks is False


# --- Experimental.validate_task_mode ---


def test_validate_task_mode_always_with_task_is_valid() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode("always", raise_error=False)
    assert error is None


def test_validate_task_mode_always_without_task_returns_error() -> None:
    exp = Experimental(task_metadata=None)
    error = exp.validate_task_mode("always", raise_error=False)
    assert error is not None
    assert error.code == METHOD_NOT_FOUND
    assert "requires task-augmented" in error.message


def test_validate_task_mode_always_without_task_raises_by_default() -> None:
    exp = Experimental(task_metadata=None)
    with pytest.raises(McpError) as exc_info:
        exp.validate_task_mode("always")
    assert exc_info.value.error.code == METHOD_NOT_FOUND


def test_validate_task_mode_never_without_task_is_valid() -> None:
    exp = Experimental(task_metadata=None)
    error = exp.validate_task_mode("never", raise_error=False)
    assert error is None


def test_validate_task_mode_never_with_task_returns_error() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode("never", raise_error=False)
    assert error is not None
    assert error.code == METHOD_NOT_FOUND
    assert "does not support task-augmented" in error.message


def test_validate_task_mode_never_with_task_raises_by_default() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    with pytest.raises(McpError) as exc_info:
        exp.validate_task_mode("never")
    assert exc_info.value.error.code == METHOD_NOT_FOUND


def test_validate_task_mode_none_treated_as_never() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode(None, raise_error=False)
    assert error is not None
    assert "does not support task-augmented" in error.message


def test_validate_task_mode_optional_with_task_is_valid() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode("optional", raise_error=False)
    assert error is None


def test_validate_task_mode_optional_without_task_is_valid() -> None:
    exp = Experimental(task_metadata=None)
    error = exp.validate_task_mode("optional", raise_error=False)
    assert error is None


# --- Experimental.validate_for_tool ---


def test_validate_for_tool_with_execution_always() -> None:
    exp = Experimental(task_metadata=None)
    tool = Tool(
        name="test",
        description="test",
        inputSchema={"type": "object"},
        execution=ToolExecution(task="always"),
    )
    error = exp.validate_for_tool(tool, raise_error=False)
    assert error is not None
    assert "requires task-augmented" in error.message


def test_validate_for_tool_without_execution() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    tool = Tool(
        name="test",
        description="test",
        inputSchema={"type": "object"},
        execution=None,
    )
    error = exp.validate_for_tool(tool, raise_error=False)
    assert error is not None
    assert "does not support task-augmented" in error.message


def test_validate_for_tool_optional_with_task() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    tool = Tool(
        name="test",
        description="test",
        inputSchema={"type": "object"},
        execution=ToolExecution(task="optional"),
    )
    error = exp.validate_for_tool(tool, raise_error=False)
    assert error is None


# --- Experimental.can_use_tool ---


def test_can_use_tool_always_with_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities(tasks=ClientTasksCapability()))
    assert exp.can_use_tool("always") is True


def test_can_use_tool_always_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool("always") is False


def test_can_use_tool_optional_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool("optional") is True


def test_can_use_tool_never_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool("never") is True


def test_can_use_tool_none_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool(None) is True
