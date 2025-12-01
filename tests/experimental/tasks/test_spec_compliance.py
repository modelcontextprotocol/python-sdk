"""
Tasks Spec Compliance Tests
===========================

Test structure mirrors: https://modelcontextprotocol.io/specification/draft/basic/utilities/tasks.md

Each section contains tests for normative requirements (MUST/SHOULD/MAY).
"""

from datetime import datetime, timezone

import pytest

from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.shared.experimental.tasks.helpers import MODEL_IMMEDIATE_RESPONSE_KEY
from mcp.types import (
    CancelTaskRequest,
    CancelTaskResult,
    CreateTaskResult,
    GetTaskRequest,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    ServerCapabilities,
    Task,
)

# Shared test datetime
TEST_DATETIME = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _get_capabilities(server: Server) -> ServerCapabilities:
    """Helper to get capabilities from a server."""
    return server.get_capabilities(
        notification_options=NotificationOptions(),
        experimental_capabilities={},
    )


def test_server_without_task_handlers_has_no_tasks_capability() -> None:
    """Server without any task handlers has no tasks capability."""
    server: Server = Server("test")
    caps = _get_capabilities(server)
    assert caps.tasks is None


def test_server_with_list_tasks_handler_declares_list_capability() -> None:
    """Server with list_tasks handler declares tasks.list capability."""
    server: Server = Server("test")

    @server.experimental.list_tasks()
    async def handle_list(req: ListTasksRequest) -> ListTasksResult:
        raise NotImplementedError

    caps = _get_capabilities(server)
    assert caps.tasks is not None
    assert caps.tasks.list is not None


def test_server_with_cancel_task_handler_declares_cancel_capability() -> None:
    """Server with cancel_task handler declares tasks.cancel capability."""
    server: Server = Server("test")

    @server.experimental.cancel_task()
    async def handle_cancel(req: CancelTaskRequest) -> CancelTaskResult:
        raise NotImplementedError

    caps = _get_capabilities(server)
    assert caps.tasks is not None
    assert caps.tasks.cancel is not None


def test_server_with_get_task_handler_declares_requests_tools_call_capability() -> None:
    """
    Server with get_task handler declares tasks.requests.tools.call capability.
    (get_task is required for task-augmented tools/call support)
    """
    server: Server = Server("test")

    @server.experimental.get_task()
    async def handle_get(req: GetTaskRequest) -> GetTaskResult:
        raise NotImplementedError

    caps = _get_capabilities(server)
    assert caps.tasks is not None
    assert caps.tasks.requests is not None
    assert caps.tasks.requests.tools is not None


def test_server_without_list_handler_has_no_list_capability() -> None:
    """Server without list_tasks handler has no tasks.list capability."""
    server: Server = Server("test")

    # Register only get_task (not list_tasks)
    @server.experimental.get_task()
    async def handle_get(req: GetTaskRequest) -> GetTaskResult:
        raise NotImplementedError

    caps = _get_capabilities(server)
    assert caps.tasks is not None
    assert caps.tasks.list is None


def test_server_without_cancel_handler_has_no_cancel_capability() -> None:
    """Server without cancel_task handler has no tasks.cancel capability."""
    server: Server = Server("test")

    # Register only get_task (not cancel_task)
    @server.experimental.get_task()
    async def handle_get(req: GetTaskRequest) -> GetTaskResult:
        raise NotImplementedError

    caps = _get_capabilities(server)
    assert caps.tasks is not None
    assert caps.tasks.cancel is None


def test_server_with_all_task_handlers_has_full_capability() -> None:
    """Server with all task handlers declares complete tasks capability."""
    server: Server = Server("test")

    @server.experimental.list_tasks()
    async def handle_list(req: ListTasksRequest) -> ListTasksResult:
        raise NotImplementedError

    @server.experimental.cancel_task()
    async def handle_cancel(req: CancelTaskRequest) -> CancelTaskResult:
        raise NotImplementedError

    @server.experimental.get_task()
    async def handle_get(req: GetTaskRequest) -> GetTaskResult:
        raise NotImplementedError

    caps = _get_capabilities(server)
    assert caps.tasks is not None
    assert caps.tasks.list is not None
    assert caps.tasks.cancel is not None
    assert caps.tasks.requests is not None
    assert caps.tasks.requests.tools is not None


class TestClientCapabilities:
    """
    Clients declare:
    - tasks.list — supports listing operations
    - tasks.cancel — supports cancellation
    - tasks.requests.sampling.createMessage — task-augmented sampling
    - tasks.requests.elicitation.create — task-augmented elicitation
    """

    def test_client_declares_tasks_capability(self) -> None:
        """Client can declare tasks capability."""
        pytest.skip("TODO")


class TestToolLevelNegotiation:
    """
    Tools in tools/list responses include execution.taskSupport with values:
    - Not present or "forbidden": No task augmentation allowed
    - "optional": Task augmentation allowed at requestor discretion
    - "required": Task augmentation is mandatory
    """

    def test_tool_execution_task_forbidden_rejects_task_augmented_call(self) -> None:
        """Tool with execution.taskSupport="forbidden" MUST reject task-augmented calls (-32601)."""
        pytest.skip("TODO")

    def test_tool_execution_task_absent_rejects_task_augmented_call(self) -> None:
        """Tool without execution.taskSupport MUST reject task-augmented calls (-32601)."""
        pytest.skip("TODO")

    def test_tool_execution_task_optional_accepts_normal_call(self) -> None:
        """Tool with execution.taskSupport="optional" accepts normal calls."""
        pytest.skip("TODO")

    def test_tool_execution_task_optional_accepts_task_augmented_call(self) -> None:
        """Tool with execution.taskSupport="optional" accepts task-augmented calls."""
        pytest.skip("TODO")

    def test_tool_execution_task_required_rejects_normal_call(self) -> None:
        """Tool with execution.taskSupport="required" MUST reject non-task calls (-32601)."""
        pytest.skip("TODO")

    def test_tool_execution_task_required_accepts_task_augmented_call(self) -> None:
        """Tool with execution.taskSupport="required" accepts task-augmented calls."""
        pytest.skip("TODO")


class TestCapabilityNegotiation:
    """
    Requestors SHOULD only augment requests with a task if the corresponding
    capability has been declared by the receiver.

    Receivers that do not declare the task capability for a request type
    MUST process requests of that type normally, ignoring any task-augmentation
    metadata if present.
    """

    def test_receiver_without_capability_ignores_task_metadata(self) -> None:
        """
        Receiver without task capability MUST process request normally,
        ignoring task-augmentation metadata.
        """
        pytest.skip("TODO")

    def test_receiver_with_capability_may_require_task_augmentation(self) -> None:
        """
        Receivers that declare task capability MAY return error (-32600)
        for non-task-augmented requests, requiring task augmentation.
        """
        pytest.skip("TODO")


class TestTaskStatusLifecycle:
    """
    Tasks begin in working status and follow valid transitions:
      working → input_required → working → terminal
      working → terminal (directly)
      input_required → terminal (directly)

    Terminal states (no further transitions allowed):
      - completed
      - failed
      - cancelled
    """

    def test_task_begins_in_working_status(self) -> None:
        """Tasks MUST begin in working status."""
        pytest.skip("TODO")

    def test_working_to_completed_transition(self) -> None:
        """working → completed is valid."""
        pytest.skip("TODO")

    def test_working_to_failed_transition(self) -> None:
        """working → failed is valid."""
        pytest.skip("TODO")

    def test_working_to_cancelled_transition(self) -> None:
        """working → cancelled is valid."""
        pytest.skip("TODO")

    def test_working_to_input_required_transition(self) -> None:
        """working → input_required is valid."""
        pytest.skip("TODO")

    def test_input_required_to_working_transition(self) -> None:
        """input_required → working is valid."""
        pytest.skip("TODO")

    def test_input_required_to_terminal_transition(self) -> None:
        """input_required → terminal is valid."""
        pytest.skip("TODO")

    def test_terminal_state_no_further_transitions(self) -> None:
        """Terminal states allow no further transitions."""
        pytest.skip("TODO")

    def test_completed_is_terminal(self) -> None:
        """completed is a terminal state."""
        pytest.skip("TODO")

    def test_failed_is_terminal(self) -> None:
        """failed is a terminal state."""
        pytest.skip("TODO")

    def test_cancelled_is_terminal(self) -> None:
        """cancelled is a terminal state."""
        pytest.skip("TODO")


class TestInputRequiredStatus:
    """
    When a receiver needs information to proceed, it moves the task to input_required.
    The requestor should call tasks/result to retrieve input requests.
    The task must include io.modelcontextprotocol/related-task metadata in associated requests.
    """

    def test_input_required_status_retrievable_via_tasks_get(self) -> None:
        """Task in input_required status is retrievable via tasks/get."""
        pytest.skip("TODO")

    def test_input_required_related_task_metadata_in_requests(self) -> None:
        """
        Task MUST include io.modelcontextprotocol/related-task metadata
        in associated requests.
        """
        pytest.skip("TODO")


class TestCreatingTask:
    """
    Request structure:
      {"method": "tools/call", "params": {"name": "...", "arguments": {...}, "task": {"ttl": 60000}}}

    Response (CreateTaskResult):
      {"result": {"task": {"taskId": "...", "status": "working", ...}}}

    Receivers may include io.modelcontextprotocol/model-immediate-response in _meta.
    """

    def test_task_augmented_request_returns_create_task_result(self) -> None:
        """Task-augmented request MUST return CreateTaskResult immediately."""
        pytest.skip("TODO")

    def test_create_task_result_contains_task_id(self) -> None:
        """CreateTaskResult MUST contain taskId."""
        pytest.skip("TODO")

    def test_create_task_result_contains_status_working(self) -> None:
        """CreateTaskResult MUST have status=working initially."""
        pytest.skip("TODO")

    def test_create_task_result_contains_created_at(self) -> None:
        """CreateTaskResult MUST contain createdAt timestamp."""
        pytest.skip("TODO")

    def test_create_task_result_created_at_is_iso8601(self) -> None:
        """createdAt MUST be ISO 8601 formatted."""
        pytest.skip("TODO")

    def test_create_task_result_may_contain_ttl(self) -> None:
        """CreateTaskResult MAY contain ttl."""
        pytest.skip("TODO")

    def test_create_task_result_may_contain_poll_interval(self) -> None:
        """CreateTaskResult MAY contain pollInterval."""
        pytest.skip("TODO")

    def test_create_task_result_may_contain_status_message(self) -> None:
        """CreateTaskResult MAY contain statusMessage."""
        pytest.skip("TODO")

    def test_receiver_may_override_requested_ttl(self) -> None:
        """Receiver MAY override requested ttl but MUST return actual value."""
        pytest.skip("TODO")

    def test_model_immediate_response_in_meta(self) -> None:
        """
        Receiver MAY include io.modelcontextprotocol/model-immediate-response
        in _meta to provide immediate response while task executes.
        """
        # Verify the constant has the correct value per spec
        assert MODEL_IMMEDIATE_RESPONSE_KEY == "io.modelcontextprotocol/model-immediate-response"

        # CreateTaskResult can include model-immediate-response in _meta
        task = Task(
            taskId="test-123",
            status="working",
            createdAt=TEST_DATETIME,
            lastUpdatedAt=TEST_DATETIME,
            ttl=60000,
        )
        immediate_msg = "Task started, processing your request..."
        # Note: Must use _meta= (alias) not meta= due to Pydantic alias handling
        result = CreateTaskResult(
            task=task,
            **{"_meta": {MODEL_IMMEDIATE_RESPONSE_KEY: immediate_msg}},
        )

        # Verify the metadata is present and correct
        assert result.meta is not None
        assert MODEL_IMMEDIATE_RESPONSE_KEY in result.meta
        assert result.meta[MODEL_IMMEDIATE_RESPONSE_KEY] == immediate_msg

        # Verify it serializes correctly with _meta alias
        serialized = result.model_dump(by_alias=True)
        assert "_meta" in serialized
        assert MODEL_IMMEDIATE_RESPONSE_KEY in serialized["_meta"]
        assert serialized["_meta"][MODEL_IMMEDIATE_RESPONSE_KEY] == immediate_msg


class TestGettingTaskStatus:
    """
    Request: {"method": "tasks/get", "params": {"taskId": "..."}}
    Response: Returns full Task object with current status and pollInterval.
    """

    def test_tasks_get_returns_task_object(self) -> None:
        """tasks/get MUST return full Task object."""
        pytest.skip("TODO")

    def test_tasks_get_returns_current_status(self) -> None:
        """tasks/get MUST return current status."""
        pytest.skip("TODO")

    def test_tasks_get_may_return_poll_interval(self) -> None:
        """tasks/get MAY return pollInterval."""
        pytest.skip("TODO")

    def test_tasks_get_invalid_task_id_returns_error(self) -> None:
        """tasks/get with invalid taskId MUST return -32602."""
        pytest.skip("TODO")

    def test_tasks_get_nonexistent_task_id_returns_error(self) -> None:
        """tasks/get with nonexistent taskId MUST return -32602."""
        pytest.skip("TODO")


class TestRetrievingResults:
    """
    Request: {"method": "tasks/result", "params": {"taskId": "..."}}
    Response: The actual operation result structure (e.g., CallToolResult).

    This call blocks until terminal status.
    """

    def test_tasks_result_returns_underlying_result(self) -> None:
        """tasks/result MUST return exactly what underlying request would return."""
        pytest.skip("TODO")

    def test_tasks_result_blocks_until_terminal(self) -> None:
        """tasks/result MUST block for non-terminal tasks."""
        pytest.skip("TODO")

    def test_tasks_result_unblocks_on_terminal(self) -> None:
        """tasks/result MUST unblock upon reaching terminal status."""
        pytest.skip("TODO")

    def test_tasks_result_includes_related_task_metadata(self) -> None:
        """tasks/result MUST include io.modelcontextprotocol/related-task in _meta."""
        pytest.skip("TODO")

    def test_tasks_result_returns_error_for_failed_task(self) -> None:
        """
        tasks/result returns the same error the underlying request
        would have produced for failed tasks.
        """
        pytest.skip("TODO")

    def test_tasks_result_invalid_task_id_returns_error(self) -> None:
        """tasks/result with invalid taskId MUST return -32602."""
        pytest.skip("TODO")


class TestListingTasks:
    """
    Request: {"method": "tasks/list", "params": {"cursor": "optional"}}
    Response: Array of tasks with pagination support via nextCursor.
    """

    def test_tasks_list_returns_array_of_tasks(self) -> None:
        """tasks/list MUST return array of tasks."""
        pytest.skip("TODO")

    def test_tasks_list_pagination_with_cursor(self) -> None:
        """tasks/list supports pagination via cursor."""
        pytest.skip("TODO")

    def test_tasks_list_returns_next_cursor_when_more_results(self) -> None:
        """tasks/list MUST return nextCursor when more results available."""
        pytest.skip("TODO")

    def test_tasks_list_cursors_are_opaque(self) -> None:
        """Implementers MUST treat cursors as opaque tokens."""
        pytest.skip("TODO")

    def test_tasks_list_invalid_cursor_returns_error(self) -> None:
        """tasks/list with invalid cursor MUST return -32602."""
        pytest.skip("TODO")


class TestCancellingTasks:
    """
    Request: {"method": "tasks/cancel", "params": {"taskId": "..."}}
    Response: Returns the task object with status: "cancelled".
    """

    def test_tasks_cancel_returns_cancelled_task(self) -> None:
        """tasks/cancel MUST return task with status=cancelled."""
        pytest.skip("TODO")

    def test_tasks_cancel_terminal_task_returns_error(self) -> None:
        """Cancelling already-terminal task MUST return -32602."""
        pytest.skip("TODO")

    def test_tasks_cancel_completed_task_returns_error(self) -> None:
        """Cancelling completed task MUST return -32602."""
        pytest.skip("TODO")

    def test_tasks_cancel_failed_task_returns_error(self) -> None:
        """Cancelling failed task MUST return -32602."""
        pytest.skip("TODO")

    def test_tasks_cancel_already_cancelled_task_returns_error(self) -> None:
        """Cancelling already-cancelled task MUST return -32602."""
        pytest.skip("TODO")

    def test_tasks_cancel_invalid_task_id_returns_error(self) -> None:
        """tasks/cancel with invalid taskId MUST return -32602."""
        pytest.skip("TODO")


class TestStatusNotifications:
    """
    Receivers MAY send: {"method": "notifications/tasks/status", "params": {...}}
    These are optional; requestors MUST NOT rely on them and SHOULD continue polling.
    """

    def test_receiver_may_send_status_notification(self) -> None:
        """Receiver MAY send notifications/tasks/status."""
        pytest.skip("TODO")

    def test_status_notification_contains_task_id(self) -> None:
        """Status notification MUST contain taskId."""
        pytest.skip("TODO")

    def test_status_notification_contains_status(self) -> None:
        """Status notification MUST contain status."""
        pytest.skip("TODO")


class TestTaskManagement:
    """
    - Receivers generate unique task IDs as strings
    - Tasks must begin in working status
    - createdAt timestamps must be ISO 8601 formatted
    - Receivers may override requested ttl but must return actual value
    - Receivers may delete tasks after TTL expires
    - All task-related messages must include io.modelcontextprotocol/related-task
      in _meta except for tasks/get, tasks/list, tasks/cancel operations
    """

    def test_task_ids_are_unique_strings(self) -> None:
        """Receivers MUST generate unique task IDs as strings."""
        pytest.skip("TODO")

    def test_multiple_tasks_have_unique_ids(self) -> None:
        """Multiple tasks MUST have unique IDs."""
        pytest.skip("TODO")

    def test_receiver_may_delete_tasks_after_ttl(self) -> None:
        """Receivers MAY delete tasks after TTL expires."""
        pytest.skip("TODO")

    def test_related_task_metadata_in_task_messages(self) -> None:
        """
        All task-related messages MUST include io.modelcontextprotocol/related-task
        in _meta.
        """
        pytest.skip("TODO")

    def test_tasks_get_does_not_require_related_task_metadata(self) -> None:
        """tasks/get does not require related-task metadata."""
        pytest.skip("TODO")

    def test_tasks_list_does_not_require_related_task_metadata(self) -> None:
        """tasks/list does not require related-task metadata."""
        pytest.skip("TODO")

    def test_tasks_cancel_does_not_require_related_task_metadata(self) -> None:
        """tasks/cancel does not require related-task metadata."""
        pytest.skip("TODO")


class TestResultHandling:
    """
    - Receivers must return CreateTaskResult immediately upon accepting task-augmented requests
    - tasks/result must return exactly what the underlying request would return
    - tasks/result blocks for non-terminal tasks; must unblock upon reaching terminal status
    """

    def test_create_task_result_returned_immediately(self) -> None:
        """Receiver MUST return CreateTaskResult immediately (not after work completes)."""
        pytest.skip("TODO")

    def test_tasks_result_matches_underlying_result_structure(self) -> None:
        """tasks/result MUST return same structure as underlying request."""
        pytest.skip("TODO")

    def test_tasks_result_for_tool_call_returns_call_tool_result(self) -> None:
        """tasks/result for tools/call returns CallToolResult."""
        pytest.skip("TODO")


class TestProgressTracking:
    """
    Task-augmented requests support progress notifications using the progressToken
    mechanism, which remains valid throughout the task lifetime.
    """

    def test_progress_token_valid_throughout_task_lifetime(self) -> None:
        """progressToken remains valid throughout task lifetime."""
        pytest.skip("TODO")

    def test_progress_notifications_sent_during_task_execution(self) -> None:
        """Progress notifications can be sent during task execution."""
        pytest.skip("TODO")


class TestProtocolErrors:
    """
    Protocol Errors (JSON-RPC standard codes):
    - -32600 (Invalid request): Non-task requests to endpoint requiring task augmentation
    - -32602 (Invalid params): Invalid/nonexistent taskId, invalid cursor, cancel terminal task
    - -32603 (Internal error): Server-side execution failures
    """

    def test_invalid_request_for_required_task_augmentation(self) -> None:
        """Non-task request to task-required endpoint returns -32600."""
        pytest.skip("TODO")

    def test_invalid_params_for_invalid_task_id(self) -> None:
        """Invalid taskId returns -32602."""
        pytest.skip("TODO")

    def test_invalid_params_for_nonexistent_task_id(self) -> None:
        """Nonexistent taskId returns -32602."""
        pytest.skip("TODO")

    def test_invalid_params_for_invalid_cursor(self) -> None:
        """Invalid cursor in tasks/list returns -32602."""
        pytest.skip("TODO")

    def test_invalid_params_for_cancel_terminal_task(self) -> None:
        """Attempt to cancel terminal task returns -32602."""
        pytest.skip("TODO")

    def test_internal_error_for_server_failure(self) -> None:
        """Server-side execution failure returns -32603."""
        pytest.skip("TODO")


class TestTaskExecutionErrors:
    """
    When underlying requests fail, the task moves to failed status.
    - tasks/get response should include statusMessage explaining failure
    - tasks/result returns same error the underlying request would have produced
    - For tool calls, isError: true moves task to failed status
    """

    def test_underlying_failure_moves_task_to_failed(self) -> None:
        """Underlying request failure moves task to failed status."""
        pytest.skip("TODO")

    def test_failed_task_has_status_message(self) -> None:
        """Failed task SHOULD include statusMessage explaining failure."""
        pytest.skip("TODO")

    def test_tasks_result_returns_underlying_error(self) -> None:
        """tasks/result returns same error underlying request would produce."""
        pytest.skip("TODO")

    def test_tool_call_is_error_true_moves_to_failed(self) -> None:
        """Tool call with isError: true moves task to failed status."""
        pytest.skip("TODO")


class TestTaskObject:
    """
    Task Object fields:
    - taskId: String identifier
    - status: Current execution state
    - statusMessage: Optional human-readable description
    - createdAt: ISO 8601 timestamp of creation
    - ttl: Milliseconds before potential deletion
    - pollInterval: Suggested milliseconds between polls
    """

    def test_task_has_task_id_string(self) -> None:
        """Task MUST have taskId as string."""
        pytest.skip("TODO")

    def test_task_has_status(self) -> None:
        """Task MUST have status."""
        pytest.skip("TODO")

    def test_task_status_message_is_optional(self) -> None:
        """Task statusMessage is optional."""
        pytest.skip("TODO")

    def test_task_has_created_at(self) -> None:
        """Task MUST have createdAt."""
        pytest.skip("TODO")

    def test_task_ttl_is_optional(self) -> None:
        """Task ttl is optional."""
        pytest.skip("TODO")

    def test_task_poll_interval_is_optional(self) -> None:
        """Task pollInterval is optional."""
        pytest.skip("TODO")


class TestRelatedTaskMetadata:
    """
    Related Task Metadata structure:
    {"_meta": {"io.modelcontextprotocol/related-task": {"taskId": "..."}}}
    """

    def test_related_task_metadata_structure(self) -> None:
        """Related task metadata has correct structure."""
        pytest.skip("TODO")

    def test_related_task_metadata_contains_task_id(self) -> None:
        """Related task metadata contains taskId."""
        pytest.skip("TODO")


class TestAccessAndIsolation:
    """
    - Task IDs enable access to sensitive results
    - Authorization context binding is essential where available
    - For non-authorized environments: strong entropy IDs, strict TTL limits
    """

    def test_task_bound_to_authorization_context(self) -> None:
        """
        Receivers receiving authorization context MUST bind tasks to that context.
        """
        pytest.skip("TODO")

    def test_reject_task_operations_outside_authorization_context(self) -> None:
        """
        Receivers MUST reject task operations for tasks outside
        requestor's authorization context.
        """
        pytest.skip("TODO")

    def test_non_authorized_environments_use_secure_ids(self) -> None:
        """
        For non-authorized environments, receivers SHOULD use
        cryptographically secure IDs.
        """
        pytest.skip("TODO")

    def test_non_authorized_environments_use_shorter_ttls(self) -> None:
        """
        For non-authorized environments, receivers SHOULD use shorter TTLs.
        """
        pytest.skip("TODO")


class TestResourceLimits:
    """
    Receivers should:
    - Enforce concurrent task limits per requestor
    - Implement maximum TTL constraints
    - Clean up expired tasks promptly
    """

    def test_concurrent_task_limit_enforced(self) -> None:
        """Receiver SHOULD enforce concurrent task limits per requestor."""
        pytest.skip("TODO")

    def test_maximum_ttl_constraint_enforced(self) -> None:
        """Receiver SHOULD implement maximum TTL constraints."""
        pytest.skip("TODO")

    def test_expired_tasks_cleaned_up(self) -> None:
        """Receiver SHOULD clean up expired tasks promptly."""
        pytest.skip("TODO")
