"""
Tests for TaskMessageQueue and InMemoryTaskMessageQueue.
"""

from datetime import datetime, timezone

import anyio
import pytest

from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue, QueuedMessage
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.types import JSONRPCNotification, JSONRPCRequest


@pytest.fixture
def queue() -> InMemoryTaskMessageQueue:
    return InMemoryTaskMessageQueue()


def make_request(id: int = 1, method: str = "test/method") -> JSONRPCRequest:
    return JSONRPCRequest(jsonrpc="2.0", id=id, method=method)


def make_notification(method: str = "test/notify") -> JSONRPCNotification:
    return JSONRPCNotification(jsonrpc="2.0", method=method)


class TestInMemoryTaskMessageQueue:
    @pytest.mark.anyio
    async def test_enqueue_and_dequeue(self, queue: InMemoryTaskMessageQueue) -> None:
        """Test basic enqueue and dequeue operations."""
        task_id = "task-1"
        msg = QueuedMessage(type="request", message=make_request())

        await queue.enqueue(task_id, msg)
        result = await queue.dequeue(task_id)

        assert result is not None
        assert result.type == "request"
        assert result.message.method == "test/method"

    @pytest.mark.anyio
    async def test_dequeue_empty_returns_none(self, queue: InMemoryTaskMessageQueue) -> None:
        """Dequeue from empty queue returns None."""
        result = await queue.dequeue("nonexistent-task")
        assert result is None

    @pytest.mark.anyio
    async def test_fifo_ordering(self, queue: InMemoryTaskMessageQueue) -> None:
        """Messages are dequeued in FIFO order."""
        task_id = "task-1"

        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request(1, "first")))
        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request(2, "second")))
        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request(3, "third")))

        msg1 = await queue.dequeue(task_id)
        msg2 = await queue.dequeue(task_id)
        msg3 = await queue.dequeue(task_id)

        assert msg1 is not None and msg1.message.method == "first"
        assert msg2 is not None and msg2.message.method == "second"
        assert msg3 is not None and msg3.message.method == "third"

    @pytest.mark.anyio
    async def test_separate_queues_per_task(self, queue: InMemoryTaskMessageQueue) -> None:
        """Each task has its own queue."""
        await queue.enqueue("task-1", QueuedMessage(type="request", message=make_request(1, "task1-msg")))
        await queue.enqueue("task-2", QueuedMessage(type="request", message=make_request(2, "task2-msg")))

        msg1 = await queue.dequeue("task-1")
        msg2 = await queue.dequeue("task-2")

        assert msg1 is not None and msg1.message.method == "task1-msg"
        assert msg2 is not None and msg2.message.method == "task2-msg"

    @pytest.mark.anyio
    async def test_peek_does_not_remove(self, queue: InMemoryTaskMessageQueue) -> None:
        """Peek returns message without removing it."""
        task_id = "task-1"
        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request()))

        peeked = await queue.peek(task_id)
        dequeued = await queue.dequeue(task_id)

        assert peeked is not None
        assert dequeued is not None
        assert isinstance(peeked.message, JSONRPCRequest)
        assert isinstance(dequeued.message, JSONRPCRequest)
        assert peeked.message.id == dequeued.message.id

    @pytest.mark.anyio
    async def test_is_empty(self, queue: InMemoryTaskMessageQueue) -> None:
        """Test is_empty method."""
        task_id = "task-1"

        assert await queue.is_empty(task_id) is True

        await queue.enqueue(task_id, QueuedMessage(type="notification", message=make_notification()))
        assert await queue.is_empty(task_id) is False

        await queue.dequeue(task_id)
        assert await queue.is_empty(task_id) is True

    @pytest.mark.anyio
    async def test_clear_returns_all_messages(self, queue: InMemoryTaskMessageQueue) -> None:
        """Clear removes and returns all messages."""
        task_id = "task-1"

        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request(1)))
        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request(2)))
        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request(3)))

        messages = await queue.clear(task_id)

        assert len(messages) == 3
        assert await queue.is_empty(task_id) is True

    @pytest.mark.anyio
    async def test_clear_empty_queue(self, queue: InMemoryTaskMessageQueue) -> None:
        """Clear on empty queue returns empty list."""
        messages = await queue.clear("nonexistent")
        assert messages == []

    @pytest.mark.anyio
    async def test_notification_messages(self, queue: InMemoryTaskMessageQueue) -> None:
        """Test queuing notification messages."""
        task_id = "task-1"
        msg = QueuedMessage(type="notification", message=make_notification("log/message"))

        await queue.enqueue(task_id, msg)
        result = await queue.dequeue(task_id)

        assert result is not None
        assert result.type == "notification"
        assert result.message.method == "log/message"

    @pytest.mark.anyio
    async def test_message_timestamp(self, queue: InMemoryTaskMessageQueue) -> None:
        """Messages have timestamps."""
        before = datetime.now(timezone.utc)
        msg = QueuedMessage(type="request", message=make_request())
        after = datetime.now(timezone.utc)

        assert before <= msg.timestamp <= after

    @pytest.mark.anyio
    async def test_message_with_resolver(self, queue: InMemoryTaskMessageQueue) -> None:
        """Messages can have resolvers."""
        task_id = "task-1"
        resolver: Resolver[dict[str, str]] = Resolver()

        msg = QueuedMessage(
            type="request",
            message=make_request(),
            resolver=resolver,
            original_request_id=42,
        )

        await queue.enqueue(task_id, msg)
        result = await queue.dequeue(task_id)

        assert result is not None
        assert result.resolver is resolver
        assert result.original_request_id == 42

    @pytest.mark.anyio
    async def test_cleanup_specific_task(self, queue: InMemoryTaskMessageQueue) -> None:
        """Cleanup removes specific task's data."""
        await queue.enqueue("task-1", QueuedMessage(type="request", message=make_request(1)))
        await queue.enqueue("task-2", QueuedMessage(type="request", message=make_request(2)))

        queue.cleanup("task-1")

        assert await queue.is_empty("task-1") is True
        assert await queue.is_empty("task-2") is False

    @pytest.mark.anyio
    async def test_cleanup_all(self, queue: InMemoryTaskMessageQueue) -> None:
        """Cleanup without task_id removes all data."""
        await queue.enqueue("task-1", QueuedMessage(type="request", message=make_request(1)))
        await queue.enqueue("task-2", QueuedMessage(type="request", message=make_request(2)))

        queue.cleanup()

        assert await queue.is_empty("task-1") is True
        assert await queue.is_empty("task-2") is True

    @pytest.mark.anyio
    async def test_wait_for_message_returns_immediately_if_message_exists(
        self, queue: InMemoryTaskMessageQueue
    ) -> None:
        """wait_for_message returns immediately if queue not empty."""
        task_id = "task-1"
        await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request()))

        # Should return immediately, not block
        with anyio.fail_after(1):
            await queue.wait_for_message(task_id)

    @pytest.mark.anyio
    async def test_wait_for_message_blocks_until_message(self, queue: InMemoryTaskMessageQueue) -> None:
        """wait_for_message blocks until a message is enqueued."""
        task_id = "task-1"
        received = False
        waiter_started = anyio.Event()

        async def enqueue_when_ready() -> None:
            # Wait until the waiter has started before enqueueing
            await waiter_started.wait()
            await queue.enqueue(task_id, QueuedMessage(type="request", message=make_request()))

        async def wait_for_msg() -> None:
            nonlocal received
            # Signal that we're about to start waiting
            waiter_started.set()
            await queue.wait_for_message(task_id)
            received = True

        async with anyio.create_task_group() as tg:
            tg.start_soon(wait_for_msg)
            tg.start_soon(enqueue_when_ready)

        assert received is True

    @pytest.mark.anyio
    async def test_notify_message_available_wakes_waiter(self, queue: InMemoryTaskMessageQueue) -> None:
        """notify_message_available wakes up waiting coroutines."""
        task_id = "task-1"
        notified = False
        waiter_started = anyio.Event()

        async def notify_when_ready() -> None:
            # Wait until the waiter has started before notifying
            await waiter_started.wait()
            await queue.notify_message_available(task_id)

        async def wait_for_notification() -> None:
            nonlocal notified
            # Signal that we're about to start waiting
            waiter_started.set()
            await queue.wait_for_message(task_id)
            notified = True

        async with anyio.create_task_group() as tg:
            tg.start_soon(wait_for_notification)
            tg.start_soon(notify_when_ready)

        assert notified is True

    @pytest.mark.anyio
    async def test_peek_empty_queue_returns_none(self, queue: InMemoryTaskMessageQueue) -> None:
        """Peek on empty queue returns None."""
        result = await queue.peek("nonexistent-task")
        assert result is None

    @pytest.mark.anyio
    async def test_wait_for_message_double_check_race_condition(self, queue: InMemoryTaskMessageQueue) -> None:
        """wait_for_message returns early if message arrives after event creation but before wait."""
        task_id = "task-1"

        # To test the double-check path (lines 223-225), we need a message to arrive
        # after the event is created (line 220) but before event.wait() (line 228).
        # We simulate this by injecting a message before is_empty is called the second time.

        original_is_empty = queue.is_empty
        call_count = 0

        async def is_empty_with_injection(tid: str) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 2 and tid == task_id:
                # Before second check, inject a message - this simulates a message
                # arriving between event creation and the double-check
                queue._queues[task_id] = [QueuedMessage(type="request", message=make_request())]
            return await original_is_empty(tid)

        queue.is_empty = is_empty_with_injection  # type: ignore[method-assign]

        # Should return immediately due to double-check finding the message
        with anyio.fail_after(1):
            await queue.wait_for_message(task_id)


class TestResolver:
    @pytest.mark.anyio
    async def test_set_result_and_wait(self) -> None:
        """Test basic set_result and wait flow."""
        resolver: Resolver[str] = Resolver()

        resolver.set_result("hello")
        result = await resolver.wait()

        assert result == "hello"
        assert resolver.done()

    @pytest.mark.anyio
    async def test_set_exception_and_wait(self) -> None:
        """Test set_exception raises on wait."""
        resolver: Resolver[str] = Resolver()

        resolver.set_exception(ValueError("test error"))

        with pytest.raises(ValueError, match="test error"):
            await resolver.wait()

        assert resolver.done()

    @pytest.mark.anyio
    async def test_set_result_when_already_completed_raises(self) -> None:
        """Test that set_result raises if resolver already completed."""
        resolver: Resolver[str] = Resolver()
        resolver.set_result("first")

        with pytest.raises(RuntimeError, match="already completed"):
            resolver.set_result("second")

    @pytest.mark.anyio
    async def test_set_exception_when_already_completed_raises(self) -> None:
        """Test that set_exception raises if resolver already completed."""
        resolver: Resolver[str] = Resolver()
        resolver.set_result("done")

        with pytest.raises(RuntimeError, match="already completed"):
            resolver.set_exception(ValueError("too late"))

    @pytest.mark.anyio
    async def test_done_returns_false_before_completion(self) -> None:
        """Test done() returns False before any result is set."""
        resolver: Resolver[str] = Resolver()
        assert resolver.done() is False
