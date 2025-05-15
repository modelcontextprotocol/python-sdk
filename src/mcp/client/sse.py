import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlparse

import anyio
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import aconnect_sse

import mcp.types as types
from mcp.client.auth import OAuthClientProvider, UnauthorizedError, auth
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


async def finish_auth(
    url: str,
    auth_provider: OAuthClientProvider,
    authorization_code: str,
) -> None:
    """
    Call this method after the user has finished authorizing via their user agent
    and is redirected back to the MCP client application. This will exchange the
    authorization code for an access token, enabling the next connection attempt
    to successfully auth.
    """
    if not auth_provider:
        raise UnauthorizedError("No auth provider")

    result = await auth(
        auth_provider, server_url=url, authorization_code=authorization_code
    )
    if result != "AUTHORIZED":
        raise UnauthorizedError("Failed to authorize")


@asynccontextmanager
async def sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
    auth_provider: OAuthClientProvider | None = None,
):
    """
    Client transport for SSE.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.

    Args:
        url: SSE endpoint URL
        headers: Optional HTTP headers
        timeout: HTTP request timeout in seconds
        sse_read_timeout: SSE read timeout in seconds
        auth_provider: Optional OAuth client provider for authentication
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def _auth_then_retry() -> None:
        """Perform OAuth authentication flow."""
        if not auth_provider:
            raise UnauthorizedError("No auth provider")

        result = await auth(auth_provider, server_url=url)
        if result != "AUTHORIZED":
            raise UnauthorizedError()

    async def _get_headers() -> dict[str, Any]:
        """Get headers with OAuth authorization if available."""
        auth_headers = {}
        if auth_provider:
            tokens = await auth_provider.tokens()
            if tokens:
                auth_headers["Authorization"] = f"Bearer {tokens.access_token}"

        return {**(headers or {}), **auth_headers}

    async with anyio.create_task_group() as tg:
        try:
            logger.info(f"Connecting to SSE endpoint: {remove_request_params(url)}")
            async with create_mcp_http_client(headers=await _get_headers()) as client:
                async with aconnect_sse(
                    client,
                    "GET",
                    url,
                    timeout=httpx.Timeout(timeout, read=sse_read_timeout),
                ) as event_source:
                    # Handle OAuth authentication errors
                    if event_source.response.status_code == 401 and auth_provider:
                        try:
                            await _auth_then_retry()
                            # Retry connection with new auth headers
                            async with create_mcp_http_client(
                                headers=await _get_headers()
                            ) as retry_client:
                                async with aconnect_sse(
                                    retry_client,
                                    "GET",
                                    url,
                                    timeout=httpx.Timeout(
                                        timeout, read=sse_read_timeout
                                    ),
                                ) as retry_event_source:
                                    retry_event_source.response.raise_for_status()
                                    event_source = retry_event_source
                        except Exception as exc:
                            logger.error(f"Auth retry failed: {exc}")
                            raise
                    else:
                        event_source.response.raise_for_status()

                    logger.debug("SSE connection established")

                    async def sse_reader(
                        task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED,
                    ):
                        try:
                            async for sse in event_source.aiter_sse():
                                logger.debug(f"Received SSE event: {sse.event}")
                                match sse.event:
                                    case "endpoint":
                                        endpoint_url = urljoin(url, sse.data)
                                        logger.info(
                                            f"Received endpoint URL: {endpoint_url}"
                                        )

                                        url_parsed = urlparse(url)
                                        endpoint_parsed = urlparse(endpoint_url)
                                        if (
                                            url_parsed.netloc != endpoint_parsed.netloc
                                            or url_parsed.scheme
                                            != endpoint_parsed.scheme
                                        ):
                                            error_msg = (
                                                "Endpoint origin does not match "
                                                f"connection origin: {endpoint_url}"
                                            )
                                            logger.error(error_msg)
                                            raise ValueError(error_msg)

                                        task_status.started(endpoint_url)

                                    case "message":
                                        try:
                                            message = types.JSONRPCMessage.model_validate_json(  # noqa: E501
                                                sse.data
                                            )
                                            logger.debug(
                                                f"Received server message: {message}"
                                            )
                                        except Exception as exc:
                                            logger.error(
                                                f"Error parsing server message: {exc}"
                                            )
                                            await read_stream_writer.send(exc)
                                            continue

                                        session_message = SessionMessage(message)
                                        await read_stream_writer.send(session_message)
                                    case _:
                                        logger.warning(
                                            f"Unknown SSE event: {sse.event}"
                                        )
                        except Exception as exc:
                            logger.error(f"Error in sse_reader: {exc}")
                            await read_stream_writer.send(exc)
                        finally:
                            await read_stream_writer.aclose()

                    async def post_writer(endpoint_url: str):
                        try:
                            async with write_stream_reader:
                                async for session_message in write_stream_reader:
                                    logger.debug(
                                        f"Sending client message: {session_message}"
                                    )
                                    post_headers = await _get_headers()
                                    response = await client.post(
                                        endpoint_url,
                                        json=session_message.message.model_dump(
                                            by_alias=True,
                                            mode="json",
                                            exclude_none=True,
                                        ),
                                        headers=post_headers,
                                    )

                                    # Handle OAuth authentication errors
                                    if response.status_code == 401 and auth_provider:
                                        try:
                                            await _auth_then_retry()
                                            # Retry with new auth headers
                                            retry_headers = await _get_headers()
                                            response = await client.post(
                                                endpoint_url,
                                                json=session_message.message.model_dump(
                                                    by_alias=True,
                                                    mode="json",
                                                    exclude_none=True,
                                                ),
                                                headers=retry_headers,
                                            )
                                        except Exception as exc:
                                            logger.error(f"Auth retry failed: {exc}")

                                    response.raise_for_status()
                                    logger.debug(
                                        "Client message sent successfully: "
                                        f"{response.status_code}"
                                    )
                        except Exception as exc:
                            logger.error(f"Error in post_writer: {exc}")
                        finally:
                            await write_stream.aclose()

                    endpoint_url = await tg.start(sse_reader)
                    logger.info(
                        f"Starting post writer with endpoint URL: {endpoint_url}"
                    )
                    tg.start_soon(post_writer, endpoint_url)

                    try:
                        yield read_stream, write_stream
                    finally:
                        tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
