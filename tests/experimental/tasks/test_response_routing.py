"""
Tests for response routing in task-augmented flows.

This tests the ResponseRouter protocol and its integration with BaseSession
to route responses for queued task requests back to their resolvers.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock

import anyio
import pytest

from mcp.shared.experimental.tasks import (
    InMemoryTaskMessageQueue,
    InMemoryTaskStore,
    QueuedMessage,
    Resolver,
    TaskResultHandler,
)
from mcp.shared.response_router import ResponseRouter
from mcp.types import ErrorData, JSONRPCRequest, RequestId, TaskMetadata


class TestResponseRouterProtocol:
    """Test the ResponseRouter protocol."""

    def test_task_result_handler_implements_protocol(self) -> None:
        """TaskResultHandler implements ResponseRouter protocol."""
        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)

        # Verify it has the required methods
        assert hasattr(handler, "route_response")
        assert hasattr(handler, "route_error")
        assert callable(handler.route_response)
        assert callable(handler.route_error)

    def test_protocol_type_checking(self) -> None:
        """ResponseRouter can be used as a type hint."""

        def accepts_router(router: ResponseRouter) -> bool:
            return router.route_response(1, {})

        # This should type-check correctly
        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)

        # Should not raise - handler implements the protocol
        result = accepts_router(handler)
        assert result is False  # No pending request


class TestTaskResultHandlerRouting:
    """Test TaskResultHandler response and error routing."""

    @pytest.fixture
    def handler(self) -> TaskResultHandler:
        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        return TaskResultHandler(store, queue)

    def test_route_response_no_pending_request(self, handler: TaskResultHandler) -> None:
        """route_response returns False when no pending request."""
        result = handler.route_response(123, {"status": "ok"})
        assert result is False

    def test_route_error_no_pending_request(self, handler: TaskResultHandler) -> None:
        """route_error returns False when no pending request."""
        error = ErrorData(code=-32600, message="Invalid Request")
        result = handler.route_error(123, error)
        assert result is False

    @pytest.mark.anyio
    async def test_route_response_with_pending_request(self, handler: TaskResultHandler) -> None:
        """route_response delivers to waiting resolver."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id: RequestId = "task-abc-12345678"

        # Simulate what happens during _deliver_queued_messages
        handler._pending_requests[request_id] = resolver

        # Route the response
        result = handler.route_response(request_id, {"action": "accept", "content": {"name": "test"}})

        assert result is True
        assert resolver.done()
        assert await resolver.wait() == {"action": "accept", "content": {"name": "test"}}

    @pytest.mark.anyio
    async def test_route_error_with_pending_request(self, handler: TaskResultHandler) -> None:
        """route_error delivers exception to waiting resolver."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id: RequestId = "task-abc-12345678"

        handler._pending_requests[request_id] = resolver

        error = ErrorData(code=-32600, message="User declined")
        result = handler.route_error(request_id, error)

        assert result is True
        assert resolver.done()

        # Should raise McpError when awaited
        with pytest.raises(Exception) as exc_info:
            await resolver.wait()
        assert "User declined" in str(exc_info.value)

    def test_route_response_removes_from_pending(self, handler: TaskResultHandler) -> None:
        """route_response removes request from pending after routing."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id: RequestId = 42

        handler._pending_requests[request_id] = resolver
        handler.route_response(request_id, {})

        assert request_id not in handler._pending_requests

    def test_route_error_removes_from_pending(self, handler: TaskResultHandler) -> None:
        """route_error removes request from pending after routing."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id: RequestId = 42

        handler._pending_requests[request_id] = resolver
        handler.route_error(request_id, ErrorData(code=0, message="test"))

        assert request_id not in handler._pending_requests

    def test_route_response_ignores_already_done_resolver(self, handler: TaskResultHandler) -> None:
        """route_response returns False for already-resolved resolver."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        resolver.set_result({"already": "done"})
        request_id: RequestId = 42

        handler._pending_requests[request_id] = resolver
        result = handler.route_response(request_id, {"new": "data"})

        # Should return False since resolver was already done
        assert result is False

    def test_route_with_string_request_id(self, handler: TaskResultHandler) -> None:
        """Response routing works with string request IDs."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id = "task-abc-12345678"

        handler._pending_requests[request_id] = resolver
        result = handler.route_response(request_id, {"status": "ok"})

        assert result is True
        assert resolver.done()

    def test_route_with_int_request_id(self, handler: TaskResultHandler) -> None:
        """Response routing works with integer request IDs."""
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id = 999

        handler._pending_requests[request_id] = resolver
        result = handler.route_response(request_id, {"status": "ok"})

        assert result is True
        assert resolver.done()


class TestDeliverQueuedMessages:
    """Test that _deliver_queued_messages properly sets up response routing."""

    @pytest.mark.anyio
    async def test_request_resolver_stored_for_routing(self) -> None:
        """When delivering a request, its resolver is stored for response routing."""
        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)

        # Create a task
        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-1")

        # Create resolver and queued message
        resolver: Resolver[dict[str, Any]] = Resolver()
        request_id: RequestId = "task-1-abc12345"
        request = JSONRPCRequest(jsonrpc="2.0", id=request_id, method="elicitation/create")

        queued_msg = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await queue.enqueue(task.taskId, queued_msg)

        # Create mock session with async send_message
        mock_session = Mock()
        mock_session.send_message = AsyncMock()

        # Deliver the message
        await handler._deliver_queued_messages(task.taskId, mock_session, "outer-request-1")

        # Verify resolver is stored for routing
        assert request_id in handler._pending_requests
        assert handler._pending_requests[request_id] is resolver

    @pytest.mark.anyio
    async def test_notification_not_stored_for_routing(self) -> None:
        """Notifications don't create pending request entries."""
        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)

        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-1")

        from mcp.types import JSONRPCNotification

        notification = JSONRPCNotification(jsonrpc="2.0", method="notifications/log")
        queued_msg = QueuedMessage(type="notification", message=notification)
        await queue.enqueue(task.taskId, queued_msg)

        mock_session = Mock()
        mock_session.send_message = AsyncMock()

        await handler._deliver_queued_messages(task.taskId, mock_session, "outer-request-1")

        # No pending requests for notifications
        assert len(handler._pending_requests) == 0


class TestTaskSessionRequestIds:
    """Test TaskSession generates unique request IDs."""

    @pytest.mark.anyio
    async def test_request_ids_are_strings(self) -> None:
        """TaskSession generates string request IDs to avoid collision with BaseSession."""
        from mcp.shared.experimental.tasks import TaskSession

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        mock_session = Mock()

        task_session = TaskSession(
            session=mock_session,
            task_id="task-abc",
            store=store,
            queue=queue,
        )

        id1 = task_session._next_request_id()
        id2 = task_session._next_request_id()

        # IDs should be strings
        assert isinstance(id1, str)
        assert isinstance(id2, str)

        # IDs should be unique
        assert id1 != id2

        # IDs should contain task ID for debugging
        assert "task-abc" in id1
        assert "task-abc" in id2

    @pytest.mark.anyio
    async def test_request_ids_include_uuid_component(self) -> None:
        """Request IDs include a UUID component for uniqueness."""
        from mcp.shared.experimental.tasks import TaskSession

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        mock_session = Mock()

        # Create two task sessions with same task_id
        task_session1 = TaskSession(session=mock_session, task_id="task-1", store=store, queue=queue)
        task_session2 = TaskSession(session=mock_session, task_id="task-1", store=store, queue=queue)

        id1 = task_session1._next_request_id()
        id2 = task_session2._next_request_id()

        # Even with same task_id, IDs should be unique due to UUID
        assert id1 != id2


class TestRelatedTaskMetadata:
    """Test that TaskSession includes related-task metadata in requests."""

    @pytest.mark.anyio
    async def test_elicit_includes_related_task_metadata(self) -> None:
        """TaskSession.elicit() includes io.modelcontextprotocol/related-task metadata."""
        from mcp.shared.experimental.tasks import RELATED_TASK_METADATA_KEY, TaskSession

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        mock_session = Mock()

        # Create a task first
        task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task-123")

        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        # Start elicitation (will block waiting for response, so we need to cancel)
        async def start_elicit() -> None:
            try:
                await task_session.elicit(
                    message="What is your name?",
                    requestedSchema={"type": "object", "properties": {"name": {"type": "string"}}},
                )
            except anyio.get_cancelled_exc_class():
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(start_elicit)
            await queue.wait_for_message(task.taskId)

            # Check the queued message
            msg = await queue.dequeue(task.taskId)
            assert msg is not None
            assert msg.type == "request"

            # Verify related-task metadata
            assert hasattr(msg.message, "params")
            params = msg.message.params
            assert params is not None
            assert "_meta" in params
            assert RELATED_TASK_METADATA_KEY in params["_meta"]
            assert params["_meta"][RELATED_TASK_METADATA_KEY]["taskId"] == task.taskId

            tg.cancel_scope.cancel()

    def test_related_task_metadata_key_value(self) -> None:
        """RELATED_TASK_METADATA_KEY has correct value per spec."""
        from mcp.shared.experimental.tasks import RELATED_TASK_METADATA_KEY

        assert RELATED_TASK_METADATA_KEY == "io.modelcontextprotocol/related-task"


class TestEndToEndResponseRouting:
    """End-to-end tests for response routing flow."""

    @pytest.mark.anyio
    async def test_full_elicitation_response_flow(self) -> None:
        """Test complete flow: enqueue -> deliver -> respond -> receive."""
        from mcp.shared.experimental.tasks import TaskSession

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)
        mock_session = Mock()

        # Create task
        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-flow-test")

        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        elicit_result = None

        async def do_elicit() -> None:
            nonlocal elicit_result
            elicit_result = await task_session.elicit(
                message="Enter name",
                requestedSchema={"type": "string"},
            )

        async def simulate_response() -> None:
            # Wait for message to be enqueued
            await queue.wait_for_message(task.taskId)

            # Simulate TaskResultHandler delivering the message
            msg = await queue.dequeue(task.taskId)
            assert msg is not None
            assert msg.resolver is not None
            assert msg.original_request_id is not None
            original_id = msg.original_request_id

            # Store resolver (as TaskResultHandler would)
            handler._pending_requests[original_id] = msg.resolver

            # Simulate client response arriving
            response_data = {"action": "accept", "content": {"name": "Alice"}}
            routed = handler.route_response(original_id, response_data)
            assert routed is True

        async with anyio.create_task_group() as tg:
            tg.start_soon(do_elicit)
            tg.start_soon(simulate_response)

        # Verify the elicit() call received the response
        assert elicit_result is not None
        assert elicit_result.action == "accept"
        assert elicit_result.content == {"name": "Alice"}

    @pytest.mark.anyio
    async def test_multiple_concurrent_elicitations(self) -> None:
        """Multiple elicitations can be routed concurrently."""
        from mcp.shared.experimental.tasks import TaskSession

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)
        mock_session = Mock()

        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-concurrent")
        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        results: list[Any] = []

        async def elicit_and_store(idx: int) -> None:
            result = await task_session.elicit(
                message=f"Question {idx}",
                requestedSchema={"type": "string"},
            )
            results.append((idx, result))

        async def respond_to_all() -> None:
            # Wait for all 3 messages to be enqueued, then respond
            for i in range(3):
                await queue.wait_for_message(task.taskId)
                msg = await queue.dequeue(task.taskId)
                if msg and msg.resolver and msg.original_request_id is not None:
                    request_id = msg.original_request_id
                    handler._pending_requests[request_id] = msg.resolver
                    handler.route_response(
                        request_id,
                        {"action": "accept", "content": {"answer": f"Response {i}"}},
                    )

        async with anyio.create_task_group() as tg:
            tg.start_soon(elicit_and_store, 0)
            tg.start_soon(elicit_and_store, 1)
            tg.start_soon(elicit_and_store, 2)
            tg.start_soon(respond_to_all)

        assert len(results) == 3
        # All should have received responses
        for _idx, result in results:
            assert result.action == "accept"


class TestSamplingResponseRouting:
    """Test sampling request/response routing through TaskSession."""

    @pytest.mark.anyio
    async def test_create_message_enqueues_request(self) -> None:
        """create_message() enqueues a sampling request."""
        from mcp.shared.experimental.tasks import TaskSession
        from mcp.types import SamplingMessage, TextContent

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        mock_session = Mock()

        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-sampling-1")

        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        async def start_sampling() -> None:
            try:
                await task_session.create_message(
                    messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
                    max_tokens=100,
                )
            except anyio.get_cancelled_exc_class():
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(start_sampling)
            await queue.wait_for_message(task.taskId)

            # Verify message was enqueued
            msg = await queue.dequeue(task.taskId)
            assert msg is not None
            assert msg.type == "request"
            assert msg.message.method == "sampling/createMessage"

            tg.cancel_scope.cancel()

    @pytest.mark.anyio
    async def test_create_message_includes_related_task_metadata(self) -> None:
        """Sampling request includes io.modelcontextprotocol/related-task metadata."""
        from mcp.shared.experimental.tasks import RELATED_TASK_METADATA_KEY, TaskSession
        from mcp.types import SamplingMessage, TextContent

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        mock_session = Mock()

        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-sampling-meta")

        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        async def start_sampling() -> None:
            try:
                await task_session.create_message(
                    messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Test"))],
                    max_tokens=50,
                )
            except anyio.get_cancelled_exc_class():
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(start_sampling)
            await queue.wait_for_message(task.taskId)

            msg = await queue.dequeue(task.taskId)
            assert msg is not None

            # Verify related-task metadata
            params = msg.message.params
            assert params is not None
            assert "_meta" in params
            assert RELATED_TASK_METADATA_KEY in params["_meta"]
            assert params["_meta"][RELATED_TASK_METADATA_KEY]["taskId"] == task.taskId

            tg.cancel_scope.cancel()

    @pytest.mark.anyio
    async def test_create_message_response_routing(self) -> None:
        """Response to sampling request is routed back to resolver."""
        from mcp.shared.experimental.tasks import TaskSession
        from mcp.types import SamplingMessage, TextContent

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)
        mock_session = Mock()

        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-sampling-route")

        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        sampling_result = None

        async def do_sampling() -> None:
            nonlocal sampling_result
            sampling_result = await task_session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text="What is 2+2?"))],
                max_tokens=100,
            )

        async def simulate_response() -> None:
            await queue.wait_for_message(task.taskId)

            msg = await queue.dequeue(task.taskId)
            assert msg is not None
            assert msg.resolver is not None
            assert msg.original_request_id is not None
            original_id = msg.original_request_id

            handler._pending_requests[original_id] = msg.resolver

            # Simulate sampling response
            response_data = {
                "model": "test-model",
                "role": "assistant",
                "content": {"type": "text", "text": "4"},
            }
            routed = handler.route_response(original_id, response_data)
            assert routed is True

        async with anyio.create_task_group() as tg:
            tg.start_soon(do_sampling)
            tg.start_soon(simulate_response)

        assert sampling_result is not None
        assert sampling_result.model == "test-model"
        assert sampling_result.role == "assistant"

    @pytest.mark.anyio
    async def test_create_message_updates_task_status(self) -> None:
        """create_message() updates task status to input_required then back to working."""
        from mcp.shared.experimental.tasks import TaskSession
        from mcp.types import SamplingMessage, TextContent

        store = InMemoryTaskStore()
        queue = InMemoryTaskMessageQueue()
        handler = TaskResultHandler(store, queue)
        mock_session = Mock()

        task = await store.create_task(TaskMetadata(ttl=60000), task_id="task-sampling-status")

        task_session = TaskSession(
            session=mock_session,
            task_id=task.taskId,
            store=store,
            queue=queue,
        )

        status_during_wait: str | None = None

        async def do_sampling() -> None:
            await task_session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hi"))],
                max_tokens=50,
            )

        async def check_status_and_respond() -> None:
            nonlocal status_during_wait
            await queue.wait_for_message(task.taskId)

            # Check status while waiting
            task_state = await store.get_task(task.taskId)
            assert task_state is not None
            status_during_wait = task_state.status

            # Respond
            msg = await queue.dequeue(task.taskId)
            assert msg is not None
            assert msg.resolver is not None
            assert msg.original_request_id is not None
            handler._pending_requests[msg.original_request_id] = msg.resolver
            handler.route_response(
                msg.original_request_id,
                {"model": "m", "role": "assistant", "content": {"type": "text", "text": "Hi"}},
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(do_sampling)
            tg.start_soon(check_status_and_respond)

        # Verify status was input_required during wait
        assert status_during_wait == "input_required"

        # Verify status is back to working after
        final_task = await store.get_task(task.taskId)
        assert final_task is not None
        assert final_task.status == "working"
