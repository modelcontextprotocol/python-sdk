from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from logging import getLogger
from time import time
from types import TracebackType
from typing import Any
from uuid import uuid4

import anyio
import anyio.to_thread
from anyio.from_thread import BlockingPortal, BlockingPortalProvider

from mcp import types
from mcp.server.auth.middleware.auth_context import auth_context_var as user_context
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext

logger = getLogger(__name__)


@dataclass
class InProgress:
    token: str
    user: AuthenticatedUser | None = None
    future: Future[types.CallToolResult] | None = None
    sessions: dict[int, ServerSession] = field(default_factory=lambda: {})
    session_progress: dict[int, types.ProgressToken | None] = field(
        default_factory=lambda: {}
    )


class ResultCache:
    """
    Note this class is a work in progress
    Its purpose is to act as a central point for managing in progress
    async calls, allowing multiple clients to join and receive progress
    updates, get results and/or cancel in progress calls
    TODO CRITICAL keep_alive logic is not correct as per spec - results currently
    only kept for as long as longest session reintroduce TTL cache
    TODO MAJOR needs a lot more testing around edge cases/failure scenarios
    TODO MAJOR decide if async.Locks are required for integrity of internal
    data structures
    TODO ENHANCEMENT externalise cachetools to allow for other implementations
    e.g. redis etal for production scenarios
    TODO ENHANCEMENT may need to add an authorisation layer to decide if
    a user is allowed to get/join/cancel an existing async call current
    simple logic only allows same user to perform these tasks
    TODO TRIVIAL name is probably not quite right, more of a result broker?
    """

    _in_progress: dict[types.AsyncToken, InProgress]
    _session_lookup: dict[int, types.AsyncToken]
    _portal: BlockingPortal

    def __init__(self, max_size: int, max_keep_alive: int):
        self._max_size = max_size
        self._max_keep_alive = max_keep_alive
        self._in_progress = {}
        self._session_lookup = {}
        self._portal_provider = BlockingPortalProvider()

    async def __aenter__(self):
        def create_portal():
            self._portal = self._portal_provider.__enter__()

        await anyio.to_thread.run_sync(create_portal)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await anyio.to_thread.run_sync(lambda: self._portal_provider.__exit__)

    async def start_call(
        self,
        call: Callable[[types.CallToolRequest], Awaitable[types.ServerResult]],
        req: types.CallToolAsyncRequest,
        ctx: RequestContext[ServerSession, Any, Any],
    ) -> types.CallToolAsyncResult:
        in_progress = await self._new_in_progress()
        timeout = min(
            req.params.keepAlive or self._max_keep_alive, self._max_keep_alive
        )

        async def call_tool():
            result = await call(
                types.CallToolRequest(
                    method="tools/call",
                    params=types.CallToolRequestParams(
                        name=req.params.name,
                        arguments=req.params.arguments,
                        _meta=req.params.meta,
                    ),
                )
            )
            # async with self._lock:
            assert type(result.root) is types.CallToolResult
            logger.debug(f"Got result {result}")
            return result.root

        in_progress.user = user_context.get()
        session_id = id(ctx.session)
        in_progress.sessions[session_id] = ctx.session
        if req.params.meta is not None:
            progress_token = req.params.meta.progressToken
        else:
            progress_token = None
        in_progress.session_progress[session_id] = progress_token
        self._session_lookup[session_id] = in_progress.token
        in_progress.future = self._portal.start_task_soon(call_tool)
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
        ctx: RequestContext[ServerSession, Any, Any],
    ) -> types.CallToolAsyncResult:
        # async with self._lock:
        in_progress = self._in_progress.get(req.params.token)
        if in_progress is None:
            # TODO consider creating new token to allow client
            # to get message describing why it wasn't accepted
            logger.warning("Discarding join request for unknown async token")
            return types.CallToolAsyncResult(accepted=False)
        else:
            # TODO consider adding authorisation layer to make this decision
            if in_progress.user == user_context.get():
                session_id = id(ctx.session)
                logger.debug(f"Received join from {session_id}")
                self._session_lookup[session_id] = req.params.token
                in_progress.sessions[session_id] = ctx.session
                if req.params.meta is not None:
                    progress_token = req.params.meta.progressToken
                else:
                    progress_token = None
                in_progress.session_progress[session_id] = progress_token
                return types.CallToolAsyncResult(token=req.params.token, accepted=True)
            else:
                # TODO consider sending error via get result
                return types.CallToolAsyncResult(accepted=False)

    async def cancel(self, notification: types.CancelToolAsyncNotification) -> None:
        # async with self._lock:
        in_progress = self._in_progress.get(notification.params.token)
        if in_progress is not None:
            if in_progress.user == user_context.get():
                # in_progress.task_group.cancel_scope.cancel()
                del self._in_progress[notification.params.token]
            else:
                logger.warning(
                    "Permission denied for cancel notification received"
                    f"from {user_context.get()}"
                )

    async def get_result(self, req: types.GetToolAsyncResultRequest):
        logger.debug("Getting result")
        in_progress = self._in_progress.get(req.params.token)
        logger.debug(f"Found in progress {in_progress}")
        if in_progress is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Unknown progress token")],
                isError=True,
            )
        else:
            if in_progress.user == user_context.get():
                if in_progress.future is None:
                    return types.CallToolResult(
                        content=[
                            types.TextContent(type="text", text="Permission denied")
                        ],
                        isError=True,
                    )
                else:
                    # TODO add timeout to get async result
                    try:
                        result = in_progress.future.result(1)
                        logger.debug(f"Found result {result}")
                        return result
                    except TimeoutError:
                        return types.CallToolResult(
                            content=[],
                            isPending=True,
                        )
            else:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="Permission denied")],
                    isError=True,
                )

    async def notification_hook(
        self, session: ServerSession, notification: types.ServerNotification
    ):
        logger.debug(f"received {notification} from {id(session)}")
        if type(notification.root) is types.ProgressNotification:
            # async with self._lock:
            async_token = self._session_lookup.get(id(session))
            if async_token is None:
                # not all sessions are async so just debug
                logger.debug("Discarding progress notification from unknown session")
            else:
                in_progress = self._in_progress.get(async_token)
                assert in_progress is not None
                for other_id, other_session in in_progress.sessions.items():
                    logger.debug(f"Checking {other_id} == {id(session)}")
                    if not other_id == id(session):
                        logger.debug(f"Sending progress to {other_id}")
                        progress_token = in_progress.session_progress.get(other_id)
                        assert progress_token is not None
                        await other_session.send_progress_notification(
                            # TODO this token is incorrect
                            # it needs to be collected from original request
                            progress_token=progress_token,
                            progress=notification.root.params.progress,
                            total=notification.root.params.total,
                            message=notification.root.params.message,
                            resource_uri=notification.root.params.resourceUri,
                        )

    async def session_close_hook(self, session: ServerSession):
        logger.debug(f"Closing {id(session)}")
        dropped = self._session_lookup.pop(id(session), None)
        if dropped is None:
            logger.warning(f"Discarding callback from unknown session {id(session)}")
        else:
            in_progress = self._in_progress.get(dropped)
            if in_progress is None:
                logger.warning("In progress not found")
            else:
                found = in_progress.sessions.pop(id(session), None)
                if found is None:
                    logger.warning("No session found")
                if len(in_progress.sessions) == 0:
                    self._in_progress.pop(dropped, None)
                    logger.debug("In progress found")
                    if in_progress.future is None:
                        logger.warning("In progress future is none")
                    else:
                        logger.debug("Cancelled in progress future")
                        in_progress.future.cancel()

    async def _new_in_progress(self) -> InProgress:
        while True:
            # this nonsense is required to protect against the
            # ridiculously unlikely scenario that two v4 uuids
            # are generated with the same value
            # uuidv7 would fix this but it is not yet included
            # in python standard library
            # see https://github.com/python/cpython/issues/89083
            # for context
            token = str(uuid4())
            if token not in self._in_progress:
                new_in_progress = InProgress(token)
                self._in_progress[token] = new_in_progress
                return new_in_progress
