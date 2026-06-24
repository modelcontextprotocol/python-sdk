import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import anyio
import httpx
from anyio.abc import TaskStatus
from httpx_sse import SSEError, aconnect_sse

from mcp import types
from mcp.shared._compat import resync_tracer
from mcp.shared._context_streams import create_context_streams
from mcp.shared._httpx_utils import McpHttpClientFactory, create_mcp_http_client
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


def _extract_session_id_from_endpoint(endpoint_url: str) -> str | None:
    query_params = parse_qs(urlparse(endpoint_url).query)
    return query_params.get("sessionId", [None])[0] or query_params.get("session_id", [None])[0]


def _path_segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _resolve_prefixed_path(sse_path: str, endpoint_path: str) -> str:
    sse_dir = sse_path.rstrip("/").rsplit("/", 1)[0]
    if not sse_dir:
        return endpoint_path

    sse_segments = _path_segments(sse_dir)
    endpoint_segments = _path_segments(endpoint_path)

    # The backend may emit its route path (for example /v1/messages) while the
    # public SSE URL includes a gateway prefix (/gateway/deployment/v1/sse).
    # Only infer a prefix when the paths overlap; no-overlap absolute paths are
    # ambiguous and retain normal origin-rooted URL semantics.
    overlap = 0
    for overlap_size in range(min(len(sse_segments), len(endpoint_segments)), 0, -1):
        if sse_segments[-overlap_size:] == endpoint_segments[:overlap_size]:
            overlap = overlap_size
            break

    if overlap == 0:
        return endpoint_path

    prefix_segments = sse_segments[: len(sse_segments) - overlap]
    if not prefix_segments:
        return endpoint_path

    return f"/{'/'.join(prefix_segments)}{endpoint_path}"


def _resolve_endpoint_url(url: str, endpoint: str) -> str:
    endpoint_parsed = urlparse(endpoint)
    if endpoint_parsed.scheme or endpoint_parsed.netloc:
        return urljoin(url, endpoint)

    if not endpoint_parsed.path.startswith("/"):
        return urljoin(url, endpoint)

    url_parsed = urlparse(url)
    endpoint_path = _resolve_prefixed_path(url_parsed.path, endpoint_parsed.path)
    return urlunparse(
        (
            url_parsed.scheme,
            url_parsed.netloc,
            endpoint_path,
            endpoint_parsed.params,
            endpoint_parsed.query,
            endpoint_parsed.fragment,
        )
    )


@asynccontextmanager
async def sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5.0,
    sse_read_timeout: float = 300.0,
    httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
    auth: httpx.Auth | None = None,
    on_session_created: Callable[[str], None] | None = None,
):
    """Client transport for SSE.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.

    Args:
        url: The SSE endpoint URL.
        headers: Optional headers to include in requests.
        timeout: HTTP timeout for regular operations (in seconds).
        sse_read_timeout: Timeout for SSE read operations (in seconds).
        httpx_client_factory: Factory function for creating the HTTPX client.
        auth: Optional HTTPX authentication handler.
        on_session_created: Optional callback invoked with the session ID when received.
    """
    logger.debug(f"Connecting to SSE endpoint: {remove_request_params(url)}")
    async with httpx_client_factory(
        headers=headers, auth=auth, timeout=httpx.Timeout(timeout, read=sse_read_timeout)
    ) as client:
        async with aconnect_sse(client, "GET", url) as event_source:
            event_source.response.raise_for_status()
            logger.debug("SSE connection established")

            read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
            write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

            async def sse_reader(task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED):
                try:
                    async for sse in event_source.aiter_sse():  # pragma: no branch
                        logger.debug(f"Received SSE event: {sse.event}")
                        match sse.event:
                            case "endpoint":
                                endpoint_url = _resolve_endpoint_url(url, sse.data)
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
                                    message = types.jsonrpc_message_adapter.validate_json(sse.data, by_name=False)
                                    logger.debug(f"Received server message: {message}")
                                except Exception as exc:  # pragma: no cover
                                    logger.exception("Error parsing server message")  # pragma: no cover
                                    await read_stream_writer.send(exc)  # pragma: no cover
                                    continue  # pragma: no cover

                                session_message = SessionMessage(message)
                                await read_stream_writer.send(session_message)
                            case _:  # pragma: no cover
                                logger.warning(f"Unknown SSE event: {sse.event}")  # pragma: no cover
                except SSEError as sse_exc:  # pragma: lax no cover
                    logger.exception("Encountered SSE exception")
                    raise sse_exc
                except Exception as exc:  # pragma: lax no cover
                    logger.exception("Error in sse_reader")
                    await read_stream_writer.send(exc)
                finally:
                    await read_stream_writer.aclose()

            async def post_writer(endpoint_url: str):
                try:
                    async with write_stream_reader, write_stream:

                        async def _send_message(session_message: SessionMessage) -> None:
                            logger.debug(f"Sending client message: {session_message}")
                            response = await client.post(
                                endpoint_url,
                                json=session_message.message.model_dump(
                                    by_alias=True,
                                    mode="json",
                                    exclude_unset=True,
                                ),
                            )
                            response.raise_for_status()
                            logger.debug(f"Client message sent successfully: {response.status_code}")

                        async for session_message in write_stream_reader:
                            sender_ctx = write_stream_reader.last_context
                            if sender_ctx is not None:
                                async with anyio.create_task_group() as tg:
                                    sender_ctx.run(tg.start_soon, _send_message, session_message)
                            else:
                                await _send_message(session_message)  # pragma: no cover
                except Exception:  # pragma: lax no cover
                    logger.exception("Error in post_writer")

            # On Python 3.14, coverage.py reports a phantom branch arc on this
            # line (->yield) when nested two async-with levels deep. The branch
            # is the unreachable "did __aexit__ suppress?" arm for memory streams.
            async with (  # pragma: no branch
                read_stream_writer,
                read_stream,
                write_stream,
                write_stream_reader,
                anyio.create_task_group() as tg,
            ):
                endpoint_url = await tg.start(sse_reader)
                logger.debug(f"Starting post writer with endpoint URL: {endpoint_url}")
                tg.start_soon(post_writer, endpoint_url)

                yield read_stream, write_stream
                tg.cancel_scope.cancel()
            await resync_tracer()
