from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4

from anyio import Lock, create_task_group, move_on_after
from anyio.abc import TaskGroup
from cachetools import TTLCache

from mcp import types
from mcp.shared.context import BaseSession, RequestContext, SessionT


@dataclass
class InProgress:
    token: str
    task_group: TaskGroup | None = None
    sessions: list[BaseSession[Any, Any, Any, Any, Any]] = field(
        default_factory=lambda: []
    )


class ResultCache:
    """
    Note this class is a work in progress
    Its purpose is to act as a central point for managing in progress
    async calls, allowing multiple clients to join and receive progress
    updates, get results and/or cancel in progress calls
    TODO CRITICAL!! Decide how to limit Async tokens for security purposes
    suggest use authentication protocol for identity - may need to add an 
    authorisation layer to decide if a user is allowed to join an existing 
    async call
    TODO name is probably not quite right, more of a result broker?
    TODO externalise cachetools to allow for other implementations
    e.g. redis etal for production scenarios
    TODO properly support join nothing actually happens at the moment
    TODO intercept progress notifications from original session and pass to joined
    sessions
    TODO handle session closure gracefully -
    at the moment old connections will hang around and cause problems later
    TODO keep_alive logic is not correct as per spec - results are cached for too long,
    probably better than too short
    TODO needs a lot more testing around edge cases/failure scenarios
    TODO might look into more fine grained locks, one global lock is a bottleneck
    though this could be delegated to other cache impls if external
    """

    _in_progress: dict[types.AsyncToken, InProgress]

    def __init__(self, max_size: int, max_keep_alive: int):
        self._max_size = max_size
        self._max_keep_alive = max_keep_alive
        self._result_cache = TTLCache[types.AsyncToken, types.CallToolResult](
            self._max_size, self._max_keep_alive
        )
        self._in_progress = {}
        self._lock = Lock()

    async def add_call(
        self,
        call: Callable[[types.CallToolRequest], Awaitable[types.ServerResult]],
        req: types.CallToolAsyncRequest,
        ctx: RequestContext[SessionT, Any, Any],
    ) -> types.CallToolAsyncResult:
        in_progress = await self._new_in_progress()
        timeout = min(
            req.params.keepAlive or self._max_keep_alive, self._max_keep_alive
        )

        async def call_tool():
            with move_on_after(timeout) as scope:
                result = await call(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name=req.params.name, arguments=req.params.arguments
                        ),
                    )
                )
            if not scope.cancel_called:
                async with self._lock:
                    assert type(result.root) is types.CallToolResult
                    self._result_cache[in_progress.token] = result.root

        async with create_task_group() as tg:
            tg.start_soon(call_tool)
            in_progress.task_group = tg
            in_progress.sessions.append(ctx.session)
            result = types.CallToolAsyncResult(
                token=in_progress.token,
                recieved=round(time()),
                keepAlive=timeout,
                accepted=True,
            )
            return result

    async def join_call(
        self,
        req: types.JoinCallToolAsyncRequest,
        ctx: RequestContext[SessionT, Any, Any],
    ) -> types.CallToolAsyncResult:
        async with self._lock:
            in_progress = self._in_progress.get(req.params.token)
            if in_progress is None:
                # TODO consider creating new token to allow client
                # to get message describing why it wasn't accepted
                return types.CallToolAsyncResult(accepted=False)
            else:
                in_progress.sessions.append(ctx.session)
                return types.CallToolAsyncResult(accepted=True)

        return

    async def cancel(self, notification: types.CancelToolAsyncNotification) -> None:
        async with self._lock:
            in_progress = self._in_progress.get(notification.params.token)
            if in_progress is not None and in_progress.task_group is not None:
                in_progress.task_group.cancel_scope.cancel()
                del self._in_progress[notification.params.token]

    async def get_result(self, req: types.GetToolAsyncResultRequest):
        async with self._lock:
            in_progress = self._in_progress.get(req.params.token)
            if in_progress is None:
                return types.CallToolResult(
                    content=[
                        types.TextContent(type="text", text="Unknown progress token")
                    ],
                    isError=True,
                )
            else:
                result = self._result_cache.get(in_progress.token)
                if result is None:
                    return types.CallToolResult(content=[], isPending=True)
                else:
                    return result

    async def _new_in_progress(self) -> InProgress:
        async with self._lock:
            while True:
                token = str(uuid4())
                if token not in self._in_progress:
                    new_in_progress = InProgress(token)
                    self._in_progress[token] = new_in_progress
                    return new_in_progress
