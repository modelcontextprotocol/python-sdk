import sys
from collections.abc import Callable
from typing import Any

if sys.version_info >= (3, 11):
    from builtins import BaseExceptionGroup  # pragma: no cover
else:
    from exceptiongroup import BaseExceptionGroup  # pragma: no cover

from unittest.mock import patch

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession, RequestId, SendResultT
from mcp.types import ClientNotification, ClientRequest, ClientResult, EmptyResult, ErrorData, PingRequest

ClientTransport = tuple[
    str,
    Callable[..., Any],
    Callable[[Any], tuple[MemoryObjectReceiveStream[Any], MemoryObjectSendStream[Any]]],
]


@pytest.mark.anyio
async def test_send_request_stream_cleanup():
    """Test that send_request properly cleans up streams when an exception occurs."""

    class TestSession(BaseSession[ClientRequest, ClientNotification, ClientResult, Any, Any]):
        async def _send_response(
            self, request_id: RequestId, response: SendResultT | ErrorData
        ) -> None:  # pragma: no cover
            pass

    write_stream_send, write_stream_receive = anyio.create_memory_object_stream[SessionMessage](1)
    read_stream_send, read_stream_receive = anyio.create_memory_object_stream[SessionMessage](1)

    session = TestSession(
        read_stream_receive,
        write_stream_send,
        object,
        object,
    )

    request = ClientRequest(PingRequest())

    async def mock_send(*args: Any, **kwargs: Any):
        raise RuntimeError("Simulated network error")

    initial_stream_count = len(session._response_streams)

    with patch.object(session._write_stream, "send", mock_send):
        with pytest.raises(RuntimeError):
            await session.send_request(request, EmptyResult)

    assert len(session._response_streams) == initial_stream_count

    await write_stream_send.aclose()
    await write_stream_receive.aclose()
    await read_stream_send.aclose()
    await read_stream_receive.aclose()


@pytest.fixture(params=["sse", "streamable"])
def client_transport(
    request: pytest.FixtureRequest, sse_server_url: str, streamable_server_url: str
) -> ClientTransport:
    if request.param == "sse":
        return (sse_server_url, sse_client, lambda x: (x[0], x[1]))
    else:
        return (streamable_server_url, streamable_http_client, lambda x: (x[0], x[1]))


@pytest.mark.anyio
async def test_generator_exit_on_gc_cleanup(client_transport: ClientTransport) -> None:
    """Suppress GeneratorExit from aclose() during GC cleanup (python/cpython#95571)."""
    url, client_func, unpack = client_transport
    cm = client_func(url)
    result = await cm.__aenter__()
    read_stream, write_stream = unpack(result)
    await cm.gen.aclose()
    await read_stream.aclose()
    await write_stream.aclose()


@pytest.mark.anyio
async def test_generator_exit_in_exception_group(client_transport: ClientTransport) -> None:
    """Extract GeneratorExit from BaseExceptionGroup (python/cpython#135736)."""
    url, client_func, unpack = client_transport
    async with client_func(url) as result:
        unpack(result)
        raise BaseExceptionGroup("unhandled errors in a TaskGroup", [GeneratorExit()])


@pytest.mark.anyio
async def test_generator_exit_mixed_group(client_transport: ClientTransport) -> None:
    """Extract GeneratorExit from BaseExceptionGroup, re-raise other exceptions (python/cpython#135736)."""
    url, client_func, unpack = client_transport
    with pytest.raises(BaseExceptionGroup) as exc_info:
        async with client_func(url) as result:
            unpack(result)
            raise BaseExceptionGroup("errors", [GeneratorExit(), ValueError("real error")])

    def has_generator_exit(eg: BaseExceptionGroup[Any]) -> bool:
        for e in eg.exceptions:
            if isinstance(e, GeneratorExit):
                return True  # pragma: no cover
            if isinstance(e, BaseExceptionGroup):
                if has_generator_exit(eg=e):  # type: ignore[arg-type]
                    return True  # pragma: no cover
        return False

    assert not has_generator_exit(exc_info.value)
