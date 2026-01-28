"""Notification handler for the low-level MCP server."""

from collections.abc import Awaitable, Callable
from typing import Any, Generic, Literal, overload

from typing_extensions import TypeVar

from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import (
    CancelledNotificationParams,
    NotificationParams,
    ProgressNotificationParams,
)

LifespanResultT = TypeVar("LifespanResultT", default=Any)
RequestT = TypeVar("RequestT", default=Any)

NotificationCtx = RequestContext[ServerSession, LifespanResultT, Any]


class NotificationHandler(Generic[LifespanResultT, RequestT]):
    """Handler for MCP notification methods.

    Each handler is associated with a method string (e.g. "notifications/progress") and
    an async endpoint function that receives a RequestContext and the notification params.
    """

    @overload
    def __init__(
        self,
        method: Literal["notifications/initialized"],
        handler: Callable[[NotificationCtx, NotificationParams | None], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/cancelled"],
        handler: Callable[[NotificationCtx, CancelledNotificationParams], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/progress"],
        handler: Callable[[NotificationCtx, ProgressNotificationParams], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/roots/list_changed"],
        handler: Callable[[NotificationCtx, NotificationParams | None], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: str,
        handler: Callable[[NotificationCtx, Any], Awaitable[None]],
    ) -> None: ...

    def __init__(self, method: str, handler: Callable[[NotificationCtx, Any], Awaitable[None]]) -> None:
        self.method = method
        self.handler = handler

    async def handle(self, ctx: NotificationCtx, params: Any) -> None:
        await self.handler(ctx, params)
