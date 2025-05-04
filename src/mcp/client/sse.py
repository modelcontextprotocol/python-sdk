import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import anyio
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import aconnect_sse

import mcp.types as types
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


def custom_url_join(base_url: str, endpoint: str) -> str:
    """
    Custom URL join function to handle the case where the endpoint is relative
    to a base URL. This function ensures that the base URL and endpoint are
    combined correctly, even if the endpoint is not a full URL.
    """
    # Parse the base URL
    parsed_base = urlparse(base_url)

    # Get the path prefix (e.g., '/weather')
    path_prefix = "/".join(parsed_base.path.split("/")[:-1])

    # Remove any leading slash from the endpoint
    clean_endpoint = endpoint.lstrip("/")

    # Create the new path by joining prefix and endpoint
    new_path = f"{path_prefix}/{clean_endpoint}"

    # Create a new parsed URL with the updated path
    parsed_new = parsed_base._replace(path=new_path)

    # Convert back to a string URL
    return urlunparse(parsed_new)


@asynccontextmanager
async def sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
):
    """
    Client transport for SSE.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async with anyio.create_task_group() as tg:
        try:
            logger.info(f"Connecting to SSE endpoint: {remove_request_params(url)}")

            # extract MCP server name from URL, for example: https://mcp.example.com/weather/sse
            # will extract 'weather'
            path_tokens = urlparse(url).path.split("/")
            optional_mcp_server_name = (
                path_tokens[1:-1] if len(path_tokens) > 2 else None
            )
            logger.debug(f"MCP Server name (optional): {optional_mcp_server_name}")

            async with httpx.AsyncClient(headers=headers) as client:
                async with aconnect_sse(
                    client,
                    "GET",
                    url,
                    timeout=httpx.Timeout(timeout, read=sse_read_timeout),
                ) as event_source:
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
                                        if optional_mcp_server_name:
                                            endpoint_url = custom_url_join(
                                                url, sse.data
                                            )
                                        else:
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
                                    response = await client.post(
                                        endpoint_url,
                                        json=session_message.message.model_dump(
                                            by_alias=True,
                                            mode="json",
                                            exclude_none=True,
                                        ),
                                    )
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
