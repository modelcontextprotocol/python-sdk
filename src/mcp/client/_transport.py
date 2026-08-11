"""Transport protocol for MCP clients."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from mcp_types import INTERNAL_ERROR, INVALID_REQUEST, ErrorData

from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.message import SessionMessage

__all__ = ["ReadStream", "WriteStream", "Transport", "TransportStreams"]

TransportStreams = tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]


def status_error_data(status_code: int, *, has_session: bool) -> ErrorData:
    """Map a non-2xx HTTP status on a client transport request to the error its waiting caller receives.

    A 404 while a session is held is the session-expiry signal (`INVALID_REQUEST`,
    "Session terminated"); anything else gets the generic stand-in. A call site with
    an extra status mapping (e.g. the message POST's pre-session 404) branches first.
    """
    if status_code == 404 and has_session:
        return ErrorData(code=INVALID_REQUEST, message="Session terminated")
    return ErrorData(code=INTERNAL_ERROR, message="Server returned an error response")


class Transport(AbstractAsyncContextManager[TransportStreams], Protocol):
    """Protocol for MCP transports.

    A transport is an async context manager that yields read and write streams
    for bidirectional communication with an MCP server.
    """
