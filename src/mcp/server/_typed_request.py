"""Shape-2 typed ``send_request`` for server-to-client requests.

`TypedServerRequestMixin` provides a typed `send_request(req) -> Result` over
the host's raw `Outbound.send_raw_request`. Spec server-to-client request types
have their result type inferred via per-type overloads; custom requests pass
``result_type=`` explicitly.

A `HasResult[R]` protocol (one generic signature, mapping declared on the
request type) is the cleaner long-term shape — see FOLLOWUPS.md. This per-spec
overload set is used for now to avoid touching `mcp.types`.
"""

from typing import Any, TypeVar, overload

from pydantic import BaseModel

from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.peer import dump_params
from mcp.types import (
    CreateMessageRequest,
    CreateMessageResult,
    ElicitRequest,
    ElicitResult,
    EmptyResult,
    ListRootsRequest,
    ListRootsResult,
    PingRequest,
    Request,
)

__all__ = ["TypedServerRequestMixin"]

ResultT = TypeVar("ResultT", bound=BaseModel)

_RESULT_FOR: dict[type[Request[Any, Any]], type[BaseModel]] = {
    CreateMessageRequest: CreateMessageResult,
    ElicitRequest: ElicitResult,
    ListRootsRequest: ListRootsResult,
    PingRequest: EmptyResult,
}


class TypedServerRequestMixin:
    """Typed ``send_request`` for the server-to-client request set.

    Mixed into `Connection` and the server `Context`. Each method constrains
    ``self`` to `Outbound` so any host with ``send_raw_request`` works.
    """

    @overload
    async def send_request(
        self: Outbound, req: CreateMessageRequest, *, opts: CallOptions | None = None
    ) -> CreateMessageResult: ...
    @overload
    async def send_request(self: Outbound, req: ElicitRequest, *, opts: CallOptions | None = None) -> ElicitResult: ...
    @overload
    async def send_request(
        self: Outbound, req: ListRootsRequest, *, opts: CallOptions | None = None
    ) -> ListRootsResult: ...
    @overload
    async def send_request(self: Outbound, req: PingRequest, *, opts: CallOptions | None = None) -> EmptyResult: ...
    @overload
    async def send_request(
        self: Outbound, req: Request[Any, Any], *, result_type: type[ResultT], opts: CallOptions | None = None
    ) -> ResultT: ...
    async def send_request(
        self: Outbound,
        req: Request[Any, Any],
        *,
        result_type: type[BaseModel] | None = None,
        opts: CallOptions | None = None,
    ) -> BaseModel:
        """Send a typed server-to-client request and return its typed result.

        For spec request types the result type is inferred. For custom requests
        pass ``result_type=`` explicitly.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
            KeyError: ``result_type`` omitted for a non-spec request type.
        """
        raw = await self.send_raw_request(req.method, dump_params(req.params), opts)
        cls = result_type if result_type is not None else _RESULT_FOR[type(req)]
        return cls.model_validate(raw)
