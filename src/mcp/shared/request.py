"""Pending request handling for task-based execution."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import anyio
from pydantic import BaseModel

from mcp.shared.task import is_terminal
from mcp.types import GetTaskResult

if TYPE_CHECKING:
    from mcp.shared.session import BaseSession

ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)

DEFAULT_POLLING_INTERVAL = 5.0  # 5 seconds


@dataclass
class TaskHandlerOptions:
    """Options for handling task status updates during result polling."""

    on_task_created: Callable[[], Awaitable[None]] | None = None
    """Callback invoked when the task is created."""

    on_task_status: Callable[[GetTaskResult], Awaitable[None]] | None = None
    """Callback invoked each time task status is polled."""


async def _default_handler(_: Any = None) -> None:
    """Default no-op handler."""
    pass


class PendingRequest(Generic[ReceiveResultT]):
    """
    Represents a pending request that may involve task-based execution.

    This class provides methods to wait for the result of a request,
    with optional task polling and status callbacks.
    """

    def __init__(
        self,
        session: "BaseSession[Any, Any, Any, Any, Any]",
        task_created_handle: Awaitable[None],
        result_handle: Awaitable[ReceiveResultT],
        result_type: type[ReceiveResultT],
        task_id: str | None = None,
    ) -> None:
        """
        Initialize a PendingRequest.

        Args:
            session: The session to use for task queries
            task_created_handle: Awaitable that completes when task is created
            result_handle: Awaitable that completes with the request result
            task_id: Optional task ID if this is a task-based request
        """
        self.session = session
        self.task_created_handle = task_created_handle
        self.result_handle = result_handle
        self.result_type = result_type
        self.task_id = task_id

    async def result(self, options: TaskHandlerOptions | None = None) -> ReceiveResultT:
        """
        Wait for a result, calling callbacks if provided and a task was created.

        Args:
            options: Optional callbacks for task creation and status updates

        Returns:
            The result of the request

        Raises:
            Any exception raised during request execution or task polling
        """
        options = options or TaskHandlerOptions()
        on_task_created = options.on_task_created or _default_handler
        on_task_status = options.on_task_status or _default_handler

        if self.task_id is None:
            # No task ID provided, just block for the result
            return await self.result_handle

        # Race between task-based polling and direct result
        # Whichever completes first (or fails last) is returned
        exceptions: list[Exception] = []
        completed = 0
        result: ReceiveResultT | None = None
        result_event = anyio.Event()

        async def wrapper(task: Callable[[], Awaitable[ReceiveResultT]]):
            nonlocal result, completed
            try:
                value = await task()
                if not result_event.is_set():
                    result = value
                    result_event.set()  # Task completed successfully
            except Exception as e:
                exceptions.append(e)
            finally:
                completed += 1
                if completed == 2 and not result_event.is_set():
                    # All tasks completed, none succeeded
                    result_event.set()

        async def _wait_for_result_task() -> ReceiveResultT:
            assert self.task_id
            return await self._task_handler(self.task_id, on_task_created, on_task_status)

        async with anyio.create_task_group() as tg:
            tg.start_soon(wrapper, _wait_for_result_task)
            tg.start_soon(wrapper, self._wait_for_result)

            # Wait for first success
            await result_event.wait()

            # Wait for first success or all completions
            await result_event.wait()

            # If we got a result, cancel remaining tasks
            if result is not None:
                tg.cancel_scope.cancel()

        # If no result but we have exceptions, raise them
        if result is None:
            if len(exceptions) == 1:
                raise exceptions[0]
            else:
                raise RuntimeError("All tasks failed", exceptions)

        return result

    async def _wait_for_result(self) -> ReceiveResultT:
        return await self.result_handle

    async def _task_handler(
        self,
        task_id: str,
        on_task_created: Callable[[], Awaitable[None]],
        on_task_status: Callable[[GetTaskResult], Awaitable[None]],
    ) -> ReceiveResultT:
        """
        Encapsulate polling for a result, calling on_task_status after querying the task.

        Args:
            task_id: The task ID to poll
            on_task_created: Callback invoked when task is created
            on_task_status: Callback invoked on each status poll

        Returns:
            The result of the task

        Raises:
            Exception: If task polling or result retrieval fails
        """
        # Wait for task creation notification
        await self.task_created_handle
        await on_task_created()

        # Poll for completion
        task: GetTaskResult
        while True:
            task = await self.session.get_task(task_id)
            await on_task_status(task)

            if is_terminal(task.status):
                break

            # Wait before polling again
            poll_frequency = task.pollFrequency if task.pollFrequency is not None else DEFAULT_POLLING_INTERVAL * 1000
            await anyio.sleep(poll_frequency / 1000.0)

        # Retrieve and return the result
        return await self.session.get_task_result(task_id, self.result_type)
