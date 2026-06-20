"""Compatibility names that outlived the removed v1 session layer (`BaseSession`)."""

from typing import Generic, TypeVar

from mcp.shared.dispatcher import ProgressFnT as ProgressFnT
from mcp.shared.message import MessageMetadata
from mcp.types import RequestParamsMeta

RequestId = str | int

ReceiveRequestT = TypeVar("ReceiveRequestT")
SendResultT = TypeVar("SendResultT")


class RequestResponder(Generic[ReceiveRequestT, SendResultT]):
    """Typing stub for the v1 responder; the SDK never instantiates it."""

    request_id: RequestId
    request_meta: RequestParamsMeta | None
    request: ReceiveRequestT
    message_metadata: MessageMetadata
