"""Low-level SSE (Server-Sent Events) stream parser for JSONRPCMessage."""

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from anyio.abc import ByteReceiveStream
from pydantic import ValidationError

from mcp.types import JSONRPCMessage

logger = logging.getLogger(__name__)


@dataclass
class SSEEvent:
    """Represents a single Server-Sent Event."""

    event: str = "message"
    """The event type. Defaults to 'message' if not specified in the stream."""

    data: str = ""
    """The event data, assembled from one or more 'data:' lines."""

    id: str | None = None
    """Optional event ID from the 'id:' field."""

    retry: int | None = None
    """Optional reconnection time in milliseconds from the 'retry:' field."""


@dataclass
class SSEParser:
    """
    Parser state for SSE streams.

    This class maintains the state needed to parse a continuous SSE byte stream.
    """

    _buffer: bytearray = field(default_factory=bytearray)
    """Internal buffer for incomplete lines."""

    _current_event: SSEEvent = field(default_factory=SSEEvent)
    """The event currently being assembled."""

    def _process_line(self, line: str) -> SSEEvent | None:
        """
        Process a single line from the SSE stream.

        Args:
            line: A decoded line from the stream (without newline).

        Returns:
            An SSEEvent if a complete event was assembled, None otherwise.
        """
        # Empty line indicates end of event
        if not line:
            if self._current_event.data or self._current_event.event:
                event = self._current_event
                self._current_event = SSEEvent()
                return event
            return None

        # Comment line (ignored)
        if line.startswith(":"):
            return None

        # Parse field
        if ":" in line:
            field_name, _, field_value = line.partition(":")
            # Remove leading space from field value (per SSE spec)
            if field_value.startswith(" "):
                field_value = field_value[1:]
        else:
            field_name = line
            field_value = ""

        # Update current event based on field
        match field_name:
            case "event":
                self._current_event.event = field_value
            case "data":
                if self._current_event.data:
                    self._current_event.data += "\n" + field_value
                else:
                    self._current_event.data = field_value
            case "id":
                self._current_event.id = field_value
            case "retry":
                try:
                    self._current_event.retry = int(field_value)
                except ValueError:
                    logger.debug(f"Invalid retry value: {field_value}")

        return None

    def feed(self, data: bytes) -> list[SSEEvent]:
        """
        Feed bytes into the parser and return any complete events.

        Args:
            data: Raw bytes from the stream.

        Returns:
            A list of complete SSEEvent objects.
        """
        self._buffer.extend(data)
        events: list[SSEEvent] = []

        # Process complete lines
        while True:
            # Look for newline (CR, LF, or CRLF)
            lf_pos = self._buffer.find(b"\n")
            if lf_pos == -1:
                break

            # Extract line (handle CRLF and LF)
            line_bytes = bytes(self._buffer[:lf_pos])
            if line_bytes.endswith(b"\r"):
                line_bytes = line_bytes[:-1]

            # Remove line from buffer
            del self._buffer[: lf_pos + 1]

            # Decode and process line
            try:
                line = line_bytes.decode("utf-8")
                event = self._process_line(line)
                if event is not None:
                    events.append(event)
            except UnicodeDecodeError:
                logger.exception("Failed to decode SSE line")
                continue

        return events


async def parse_sse_stream(
    stream: ByteReceiveStream,
) -> AsyncGenerator[JSONRPCMessage, None]:
    """
    Parse SSE stream from a byte stream and yield JSONRPCMessage objects.

    This async generator reads from a byte stream, parses Server-Sent Events (SSE),
    and yields JSONRPCMessage objects for events with type "message".

    The SSE format follows the W3C specification:
    - Lines starting with "event:" specify the event type
    - Lines starting with "data:" contain the event data (can span multiple lines)
    - Lines starting with "id:" specify an optional event ID
    - Blank lines indicate the end of an event
    - Lines starting with ":" are comments and are ignored

    Args:
        stream: An anyio/trio byte receive stream to read SSE data from.

    Yields:
        JSONRPCMessage objects parsed from "message" type events.

    Raises:
        ValidationError: If a message event contains invalid JSON-RPC data.

    Example:
        ```python
        async with await trio.open_tcp_stream("localhost", 8080) as stream:
            async for message in parse_sse_stream(stream):
                print(f"Received: {message}")
        ```
    """
    parser = SSEParser()

    try:
        async for chunk in stream:
            # Feed chunk to parser
            events = parser.feed(chunk)

            # Process complete events
            for event in events:
                logger.debug(f"Received SSE event: {event.event}")

                # Only parse "message" events as JSONRPCMessage
                if event.event == "message":
                    try:
                        message = JSONRPCMessage.model_validate_json(event.data)
                        logger.debug(f"Parsed JSONRPCMessage: {message}")
                        yield message
                    except ValidationError:
                        logger.exception("Failed to parse JSONRPCMessage from SSE data")
                        raise
                else:
                    # Log other event types but don't yield them
                    logger.debug(f"Skipping non-message event: {event.event}")

    except Exception:
        logger.exception("Error in SSE stream parsing")
        raise
