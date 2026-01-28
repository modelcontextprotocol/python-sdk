"""Request and notification handlers for the low-level MCP server."""

from collections.abc import Awaitable, Callable
from typing import Any, Generic, Literal, overload

from typing_extensions import TypeVar

from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    CancelledNotificationParams,
    CompleteRequestParams,
    CompleteResult,
    EmptyResult,
    GetPromptRequestParams,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    NotificationParams,
    PaginatedRequestParams,
    ProgressNotificationParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    RequestParams,
    SetLevelRequestParams,
    SubscribeRequestParams,
    UnsubscribeRequestParams,
)

LifespanResultT = TypeVar("LifespanResultT", default=Any)
RequestT = TypeVar("RequestT", default=Any)

Ctx = RequestContext[ServerSession, LifespanResultT, RequestT]


class Handler(Generic[LifespanResultT, RequestT]):
    """Base class for MCP handlers."""

    method: str

    async def handle(self, ctx: Ctx, params: Any) -> Any:
        raise NotImplementedError


class RequestHandler(Handler[LifespanResultT, RequestT]):
    """Handler for MCP request methods.

    Each handler is associated with a method string (e.g. "tools/call") and
    an async endpoint function that receives a RequestContext and the request params.
    """

    @overload
    def __init__(
        self,
        method: Literal["ping"],
        handler: Callable[[Ctx, RequestParams | None], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["prompts/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListPromptsResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["prompts/get"],
        handler: Callable[[Ctx, GetPromptRequestParams], Awaitable[GetPromptResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListResourcesResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/templates/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListResourceTemplatesResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/read"],
        handler: Callable[[Ctx, ReadResourceRequestParams], Awaitable[ReadResourceResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/subscribe"],
        handler: Callable[[Ctx, SubscribeRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/unsubscribe"],
        handler: Callable[[Ctx, UnsubscribeRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["logging/setLevel"],
        handler: Callable[[Ctx, SetLevelRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["tools/list"],
        handler: Callable[[Ctx, PaginatedRequestParams | None], Awaitable[ListToolsResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["tools/call"],
        handler: Callable[[Ctx, CallToolRequestParams], Awaitable[CallToolResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["completion/complete"],
        handler: Callable[[Ctx, CompleteRequestParams], Awaitable[CompleteResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: str,
        handler: Callable[[Ctx, Any], Awaitable[Any]],
    ) -> None: ...

    def __init__(self, method: str, handler: Callable[[Ctx, Any], Awaitable[Any]]) -> None:
        self.method = method
        self.handler = handler

    async def handle(self, ctx: Ctx, params: Any) -> Any:
        return await self.handler(ctx, params)


class NotificationHandler(Handler[LifespanResultT, RequestT]):
    """Handler for MCP notification methods.

    Each handler is associated with a method string (e.g. "notifications/progress") and
    an async endpoint function that receives a RequestContext and the notification params.
    """

    @overload
    def __init__(
        self,
        method: Literal["notifications/initialized"],
        handler: Callable[[Ctx, NotificationParams | None], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/cancelled"],
        handler: Callable[[Ctx, CancelledNotificationParams], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/progress"],
        handler: Callable[[Ctx, ProgressNotificationParams], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["notifications/roots/list_changed"],
        handler: Callable[[Ctx, NotificationParams | None], Awaitable[None]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: str,
        handler: Callable[[Ctx, Any], Awaitable[None]],
    ) -> None: ...

    def __init__(self, method: str, handler: Callable[[Ctx, Any], Awaitable[None]]) -> None:
        self.method = method
        self.handler = handler

    async def handle(self, ctx: Ctx, params: Any) -> None:
        await self.handler(ctx, params)
