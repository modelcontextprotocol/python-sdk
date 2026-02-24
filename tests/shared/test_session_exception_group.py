"""Test that BaseSession unwraps ExceptionGroups properly."""

from __future__ import annotations

import anyio
import pytest
from pydantic import TypeAdapter

from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession


class _TestSession(BaseSession):  # type: ignore[reportMissingTypeArgument]
    """Test implementation of BaseSession."""

    @property
    def _receive_request_adapter(self) -> TypeAdapter[dict[str, object]]:
        return TypeAdapter(dict)

    @property
    def _receive_notification_adapter(self) -> TypeAdapter[dict[str, object]]:
        return TypeAdapter(dict)


@pytest.mark.anyio
async def test_session_propagates_real_error_not_exception_group() -> None:
    """Test that real errors propagate unwrapped from session task groups."""
    # Create streams
    read_sender, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception]()
    write_stream, write_receiver = anyio.create_memory_object_stream[SessionMessage]()

    try:
        session = _TestSession(
            read_stream=read_stream,
            write_stream=write_stream,
            read_timeout_seconds=None,
        )

        # The session's receive loop will start in __aenter__
        # If it fails with ExceptionGroup, we want only the real error
        with pytest.raises(ConnectionError, match="connection failed"):
            async with session:
                # Raise a connection error to trigger exception group behavior
                raise ConnectionError("connection failed")

    finally:
        await read_sender.aclose()
        await read_stream.aclose()
        await write_stream.aclose()
        await write_receiver.aclose()
