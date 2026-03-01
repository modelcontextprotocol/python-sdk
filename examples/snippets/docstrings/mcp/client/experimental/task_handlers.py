"""Companion examples for src/mcp/client/experimental/task_handlers.py docstrings."""

from __future__ import annotations

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import types
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.client.session import ClientSession
from mcp.shared._context import RequestContext
from mcp.shared.session import SessionMessage


async def my_get_task_handler(
    context: RequestContext[ClientSession],
    params: types.GetTaskRequestParams,
) -> types.GetTaskResult | types.ErrorData: ...


async def my_list_tasks_handler(
    context: RequestContext[ClientSession],
    params: types.PaginatedRequestParams | None,
) -> types.ListTasksResult | types.ErrorData: ...


def ExperimentalTaskHandlers_usage(
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
) -> None:
    # region ExperimentalTaskHandlers_usage
    handlers = ExperimentalTaskHandlers(
        get_task=my_get_task_handler,
        list_tasks=my_list_tasks_handler,
    )
    session = ClientSession(read_stream, write_stream, experimental_task_handlers=handlers)
    # endregion ExperimentalTaskHandlers_usage
