"""Compatibility surface for the removed v1 session layer.

`BaseSession` (the v1 receive loop) is gone: `ClientSession` runs on
`JSONRPCDispatcher` and the server side on `ServerRunner`. This module keeps
the names that outlived it.
"""

from typing import Generic, TypeVar

from mcp.shared.dispatcher import ProgressFnT as ProgressFnT
from mcp.shared.message import MessageMetadata
from mcp.types import RequestParamsMeta

RequestId = str | int

ReceiveRequestT = TypeVar("ReceiveRequestT")
SendResultT = TypeVar("SendResultT")


class RequestResponder(Generic[ReceiveRequestT, SendResultT]):
    """Typing stub for the v1 responder.

    Never instantiated by the SDK: the client answers every server request
    itself, so the `RequestResponder` arm of `MessageHandlerFnT` is
    unreachable. The class remains so existing annotations and imports keep
    working.
    """

    request_id: RequestId
    request_meta: RequestParamsMeta | None
    request: ReceiveRequestT
    message_metadata: MessageMetadata
