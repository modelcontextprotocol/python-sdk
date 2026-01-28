"""Request handler for the low-level MCP server."""

from collections.abc import Awaitable, Callable
from typing import Any, Generic, Literal, overload

from typing_extensions import TypeVar

from mcp.server.session import ServerSession
from mcp.shared.context import RequestHandlerContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    CompleteRequestParams,
    CompleteResult,
    EmptyResult,
    GetPromptRequestParams,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    RequestParams,
    SetLevelRequestParams,
    SubscribeRequestParams,
    UnsubscribeRequestParams,
)

LifespanResultT = TypeVar("LifespanResultT", default=Any)
RequestT = TypeVar("RequestT", default=Any)

RequestCtx = RequestHandlerContext[ServerSession, LifespanResultT, RequestT]


class RequestHandler(Generic[LifespanResultT, RequestT]):
    """Handler for MCP request methods.

    Each handler is associated with a method string (e.g. "tools/call") and
    an async endpoint function that receives a RequestContext and the request params.
    """

    @overload
    def __init__(
        self,
        method: Literal["ping"],
        handler: Callable[[RequestCtx, RequestParams | None], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["prompts/list"],
        handler: Callable[[RequestCtx, PaginatedRequestParams | None], Awaitable[ListPromptsResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["prompts/get"],
        handler: Callable[[RequestCtx, GetPromptRequestParams], Awaitable[GetPromptResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/list"],
        handler: Callable[[RequestCtx, PaginatedRequestParams | None], Awaitable[ListResourcesResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/templates/list"],
        handler: Callable[[RequestCtx, PaginatedRequestParams | None], Awaitable[ListResourceTemplatesResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/read"],
        handler: Callable[[RequestCtx, ReadResourceRequestParams], Awaitable[ReadResourceResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/subscribe"],
        handler: Callable[[RequestCtx, SubscribeRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["resources/unsubscribe"],
        handler: Callable[[RequestCtx, UnsubscribeRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["logging/setLevel"],
        handler: Callable[[RequestCtx, SetLevelRequestParams], Awaitable[EmptyResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["tools/list"],
        handler: Callable[[RequestCtx, PaginatedRequestParams | None], Awaitable[ListToolsResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["tools/call"],
        handler: Callable[[RequestCtx, CallToolRequestParams], Awaitable[CallToolResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: Literal["completion/complete"],
        handler: Callable[[RequestCtx, CompleteRequestParams], Awaitable[CompleteResult]],
    ) -> None: ...

    @overload
    def __init__(
        self,
        method: str,
        handler: Callable[[RequestCtx, Any], Awaitable[Any]],
    ) -> None: ...

    def __init__(self, method: str, handler: Callable[[RequestCtx, Any], Awaitable[Any]]) -> None:
        self.method = method
        self.endpoint = handler

    async def handle(self, ctx: RequestCtx, params: Any) -> Any:
        return await self.endpoint(ctx, params)
