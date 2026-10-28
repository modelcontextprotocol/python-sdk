import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import anyio
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import SSEError

import mcp.types as types
from mcp.shared._httpx_utils import (
    McpHttpClientFactory,
    create_mcp_http_client,
    redirect_note,
    request_within_origin,
    sse_within_origin,
)
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


def _extract_session_id_from_endpoint(endpoint_url: str) -> str | None:
    query_params = parse_qs(urlparse(endpoint_url).query)
    return query_params.get("sessionId", [None])[0] or query_params.get("session_id", [None])[0]


def _status_error_data(status_code: int, *, has_session: bool) -> types.ErrorData:
    """The error a request gets when its message POST is answered with a non-2xx `status_code`.

    A 404 while the endpoint URL carries a session id means the server no longer knows the session.
    """
    if status_code == 404 and has_session:
        return types.ErrorData(code=types.INVALID_REQUEST, message="Session terminated")
    return types.ErrorData(code=types.INTERNAL_ERROR, message="Server returned an error response")


@asynccontextmanager
async def sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
    httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
    auth: httpx.Auth | None = None,
    on_session_created: Callable[[str], None] | None = None,
):
    """
    Client transport for SSE.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.

    A message POST answered with a non-2xx status, or failing without a response, resolves
    its request with a JSON-RPC error (an `McpError` for a `ClientSession` caller), and later
    messages are still sent; a failed notification is only logged.

    Args:
        url: The SSE endpoint URL.
        headers: Optional headers to include in requests.
        timeout: HTTP timeout for regular operations.
        sse_read_timeout: Timeout for SSE read operations.
        httpx_client_factory: Factory function for creating the httpx client. Whichever client it
            returns, MCP requests follow a redirect only when it stays on the endpoint's origin
            (same scheme, host and port, or http to https on the same host with default ports) and
            keeps the request method (any status for the SSE GET, 307/308 for a message POST); any
            other redirect is not followed: connecting fails with `httpx.HTTPStatusError` for the
            redirect response, and a message POST fails as for any non-2xx status. The client's
            `follow_redirects` setting is not consulted; the SDK's OAuth providers apply the same
            rule to the requests they make.
        auth: Optional HTTPX authentication handler.
        on_session_created: Optional callback invoked with the session ID when received.
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async with anyio.create_task_group() as tg:
        try:
            logger.debug(f"Connecting to SSE endpoint: {remove_request_params(url)}")
            async with httpx_client_factory(
                headers=headers, auth=auth, timeout=httpx.Timeout(timeout, read=sse_read_timeout)
            ) as client:
                async with sse_within_origin(client, url) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("SSE connection established")

                    async def sse_reader(
                        task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED,
                    ):
                        try:
                            async for sse in event_source.aiter_sse():  # pragma: no branch
                                logger.debug(f"Received SSE event: {sse.event}")
                                match sse.event:
                                    case "endpoint":
                                        endpoint_url = urljoin(url, sse.data)
                                        logger.debug(f"Received endpoint URL: {endpoint_url}")

                                        url_parsed = urlparse(url)
                                        endpoint_parsed = urlparse(endpoint_url)
                                        if (  # pragma: no cover
                                            url_parsed.netloc != endpoint_parsed.netloc
                                            or url_parsed.scheme != endpoint_parsed.scheme
                                        ):
                                            error_msg = (  # pragma: no cover
                                                f"Endpoint origin does not match connection origin: {endpoint_url}"
                                            )
                                            logger.error(error_msg)  # pragma: no cover
                                            raise ValueError(error_msg)  # pragma: no cover

                                        if on_session_created:
                                            session_id = _extract_session_id_from_endpoint(endpoint_url)
                                            if session_id:
                                                on_session_created(session_id)

                                        task_status.started(endpoint_url)

                                    case "message":
                                        # Skip empty data (keep-alive pings)
                                        if not sse.data:
                                            continue
                                        try:
                                            message = types.JSONRPCMessage.model_validate_json(  # noqa: E501
                                                sse.data
                                            )
                                            logger.debug(f"Received server message: {message}")
                                        except Exception as exc:  # pragma: no cover
                                            logger.exception("Error parsing server message")  # pragma: no cover
                                            await read_stream_writer.send(exc)  # pragma: no cover
                                            continue  # pragma: no cover

                                        session_message = SessionMessage(message)
                                        await read_stream_writer.send(session_message)
                                    case _:  # pragma: no cover
                                        logger.warning(f"Unknown SSE event: {sse.event}")  # pragma: no cover
                        except SSEError as sse_exc:  # pragma: no cover
                            logger.exception("Encountered SSE exception")  # pragma: no cover
                            raise sse_exc  # pragma: no cover
                        except Exception as exc:  # pragma: no cover
                            logger.exception("Error in sse_reader")  # pragma: no cover
                            await read_stream_writer.send(exc)  # pragma: no cover
                        finally:
                            await read_stream_writer.aclose()

                    async def resolve_request(request_id: types.RequestId, error: types.ErrorData) -> None:
                        reply = types.JSONRPCError(jsonrpc="2.0", id=request_id, error=error)
                        try:
                            await read_stream_writer.send(SessionMessage(types.JSONRPCMessage(reply)))
                        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                            # The read stream ended first, and the session fails its waiters itself then.
                            logger.debug(f"Read stream closed before request {request_id!r} could be resolved")

                    async def post_writer(endpoint_url: str):
                        has_session = _extract_session_id_from_endpoint(endpoint_url) is not None
                        try:
                            async with write_stream_reader:
                                async for session_message in write_stream_reader:
                                    logger.debug(f"Sending client message: {session_message}")
                                    message = session_message.message.root
                                    try:
                                        response = await request_within_origin(
                                            client,
                                            "POST",
                                            endpoint_url,
                                            json=session_message.message.model_dump(
                                                by_alias=True,
                                                mode="json",
                                                exclude_none=True,
                                            ),
                                        )
                                    except Exception as exc:
                                        # Beyond httpx's own errors, auth flows and event hooks can raise anything.
                                        logger.exception("Error POSTing message")
                                        error = types.ErrorData(
                                            code=types.CONNECTION_CLOSED, message=f"Failed to send message: {exc}"
                                        )
                                    else:
                                        if response.is_success:
                                            logger.debug(f"Client message sent successfully: {response.status_code}")
                                            continue
                                        logger.error(
                                            f"Message POST returned HTTP status {response.status_code}"
                                            f"{redirect_note(response)}"
                                        )
                                        error = _status_error_data(response.status_code, has_session=has_session)
                                    # A notification has no waiter, so its failure is only logged. A request's
                                    # waiter gets the error from a task of its own: ClientSession answers server
                                    # requests inline in its receive loop, which may be waiting for this loop to
                                    # send such a reply.
                                    if isinstance(message, types.JSONRPCRequest):
                                        tg.start_soon(resolve_request, message.id, error)
                        except Exception:  # pragma: no cover
                            logger.exception("Error in post_writer")  # pragma: no cover
                        finally:
                            await write_stream.aclose()

                    endpoint_url = await tg.start(sse_reader)
                    logger.debug(f"Starting post writer with endpoint URL: {endpoint_url}")
                    tg.start_soon(post_writer, endpoint_url)

                    try:
                        yield read_stream, write_stream
                    finally:
                        tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
            # The receive sides too, so that failing to connect (which raises before the
            # streams are handed to the caller) does not leave them to the garbage collector.
            await read_stream.aclose()
            await write_stream_reader.aclose()
