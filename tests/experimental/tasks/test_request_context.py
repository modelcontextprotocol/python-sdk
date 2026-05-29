"""Tests for the RequestContext.experimental (Experimental class) task validation helpers."""

import pytest

from mcp.server.experimental.request_context import Experimental
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.shared.exceptions import McpError
from mcp.types import (
    METHOD_NOT_FOUND,
    TASK_FORBIDDEN,
    TASK_OPTIONAL,
    TASK_REQUIRED,
    ClientCapabilities,
    ClientTasksCapability,
    Result,
    TaskMetadata,
    Tool,
    ToolExecution,
)


def test_is_task_true_when_metadata_present() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    assert exp.is_task is True


def test_is_task_false_when_no_metadata() -> None:
    exp = Experimental(task_metadata=None)
    assert exp.is_task is False


def test_client_supports_tasks_true() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities(tasks=ClientTasksCapability()))
    assert exp.client_supports_tasks is True


def test_client_supports_tasks_false_no_tasks() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.client_supports_tasks is False


def test_client_supports_tasks_false_no_capabilities() -> None:
    exp = Experimental(_client_capabilities=None)
    assert exp.client_supports_tasks is False


def test_validate_task_mode_required_with_task_is_valid() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode(TASK_REQUIRED, raise_error=False)
    assert error is None


def test_validate_task_mode_required_without_task_returns_error() -> None:
    exp = Experimental(task_metadata=None)
    error = exp.validate_task_mode(TASK_REQUIRED, raise_error=False)
    assert error is not None
    assert error.code == METHOD_NOT_FOUND
    assert "requires task-augmented" in error.message


def test_validate_task_mode_required_without_task_raises_by_default() -> None:
    exp = Experimental(task_metadata=None)
    with pytest.raises(McpError) as exc_info:
        exp.validate_task_mode(TASK_REQUIRED)
    assert exc_info.value.error.code == METHOD_NOT_FOUND


def test_validate_task_mode_forbidden_without_task_is_valid() -> None:
    exp = Experimental(task_metadata=None)
    error = exp.validate_task_mode(TASK_FORBIDDEN, raise_error=False)
    assert error is None


def test_validate_task_mode_forbidden_with_task_returns_error() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode(TASK_FORBIDDEN, raise_error=False)
    assert error is not None
    assert error.code == METHOD_NOT_FOUND
    assert "does not support task-augmented" in error.message


def test_validate_task_mode_forbidden_with_task_raises_by_default() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    with pytest.raises(McpError) as exc_info:
        exp.validate_task_mode(TASK_FORBIDDEN)
    assert exc_info.value.error.code == METHOD_NOT_FOUND


def test_validate_task_mode_none_treated_as_forbidden() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode(None, raise_error=False)
    assert error is not None
    assert "does not support task-augmented" in error.message


def test_validate_task_mode_optional_with_task_is_valid() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))
    error = exp.validate_task_mode(TASK_OPTIONAL, raise_error=False)
    assert error is None


def test_validate_task_mode_optional_without_task_is_valid() -> None:
    exp = Experimental(task_metadata=None)
    error = exp.validate_task_mode(TASK_OPTIONAL, raise_error=False)
    assert error is None


def test_validate_for_tool_with_execution_required() -> None:
    exp = Experimental(task_metadata=None)
    tool = Tool(
        name="test",
        description="test",
        inputSchema={"type": "object"},
        execution=ToolExecution(taskSupport=TASK_REQUIRED),
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
        execution=ToolExecution(taskSupport=TASK_OPTIONAL),
    )
    error = exp.validate_for_tool(tool, raise_error=False)
    assert error is None


def test_can_use_tool_required_with_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities(tasks=ClientTasksCapability()))
    assert exp.can_use_tool(TASK_REQUIRED) is True


def test_can_use_tool_required_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool(TASK_REQUIRED) is False


def test_can_use_tool_optional_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool(TASK_OPTIONAL) is True


def test_can_use_tool_forbidden_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool(TASK_FORBIDDEN) is True


def test_can_use_tool_none_without_task_support() -> None:
    exp = Experimental(_client_capabilities=ClientCapabilities())
    assert exp.can_use_tool(None) is True


@pytest.mark.anyio
async def test_run_task_with_an_explicit_task_id_emits_a_deprecation_warning() -> None:
    """An explicitly provided task ID is not associated with the creating session, so passing one is deprecated."""
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))

    async def work(task: ServerTaskContext) -> Result:
        raise AssertionError("unreachable")  # pragma: no cover

    with pytest.warns(DeprecationWarning, match="not associated with the session"):
        # Task support is not configured, so the call fails after the
        # deprecated argument has been reported.
        with pytest.raises(RuntimeError, match="Task support not enabled"):
            # The deliberate use of the deprecated overload is the point of this test.
            await exp.run_task(work, task_id="explicitly-chosen")  # pyright: ignore[reportDeprecated]


@pytest.mark.anyio
async def test_run_task_without_a_task_id_does_not_warn() -> None:
    exp = Experimental(task_metadata=TaskMetadata(ttl=60000))

    async def work(task: ServerTaskContext) -> Result:
        raise AssertionError("unreachable")  # pragma: no cover

    with pytest.raises(RuntimeError, match="Task support not enabled"):
        await exp.run_task(work)
