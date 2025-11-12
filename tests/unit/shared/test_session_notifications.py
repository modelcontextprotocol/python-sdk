import anyio
import pytest

import mcp.types as types
from mcp.shared.session import BaseSession, SessionMessage


class BrokenSendStream:
    def __init__(self, exception: BaseException) -> None:
        self._exception = exception

    async def send(self, message: SessionMessage) -> None:
        raise self._exception


@pytest.mark.anyio
async def test_send_notification_discards_when_stream_closed() -> None:
    read_sender, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](1)

    session = BaseSession(
        read_stream,
        write_stream,
        types.ServerRequest,
        types.ServerNotification,
    )

    original_write_stream = session._write_stream
    session._write_stream = BrokenSendStream(anyio.BrokenResourceError())  # type: ignore[assignment]

    notification = types.LoggingMessageNotification(
        params=types.LoggingMessageNotificationParams(level="info", data="message"),
    )

    await session.send_notification(notification, related_request_id=7)

    await read_sender.aclose()
    await write_reader.aclose()
    await read_stream.aclose()
    await original_write_stream.aclose()
