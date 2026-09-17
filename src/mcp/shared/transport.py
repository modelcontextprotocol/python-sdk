"""Public contracts for message transports on either side of an MCP connection."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TypeAlias

from typing_extensions import Protocol

from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import Dispatcher
from mcp.shared.message import ClientMessageMetadata, MessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.transport_context import TransportContext

__all__ = [
    "ClientMessageMetadata",
    "DispatcherTransport",
    "MessageMetadata",
    "ReadStream",
    "ServerMessageMetadata",
    "SessionMessage",
    "Transport",
    "TransportContext",
    "TransportContextBuilder",
    "TransportStreams",
    "WriteStream",
]

TransportStreams: TypeAlias = tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]
TransportContextBuilder: TypeAlias = Callable[[MessageMetadata], TransportContext]


class Transport(AbstractAsyncContextManager[TransportStreams], Protocol):
    """An async context manager yielding a logical peer's read and write streams.

    Entering opens the channel. Exiting closes owned resources and stops its
    background tasks. Consumers may close the streams before context exit, so
    stream closure must be idempotent. Borrowed network clients remain owned by
    their caller.

    Each inbound item is a decoded `SessionMessage` or a recoverable exception.
    End the read stream when the connection is lost; an exception item alone
    does not fail pending requests. Writes must support cancellation and apply
    backpressure instead of buffering indefinitely.

    A stream pair belongs to one logical peer, not an entire broker. The
    adapter owns framing and routing; the SDK owns MCP protocol processing.
    """


@dataclass(frozen=True)
class DispatcherTransport:
    """Explicitly opt into a dispatcher-backed connection instead of message streams.

    Pass this wrapper to `Client` or `ServerRuntime.connect()`. Entering
    `connection` acquires the channel and yields an unstarted dispatcher; the
    SDK owns its receive loop. Exiting releases the channel after the loop
    stops. Native adapters can use their own framing without implementing MCP
    negotiation, validation, callbacks, or a separate client-session API.

    Custom dispatcher implementations remain experimental until the lifecycle
    contract has been validated against native network bindings.
    """

    connection: AbstractAsyncContextManager[Dispatcher[TransportContext]]
