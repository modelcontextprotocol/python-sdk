import logging
from contextlib import asynccontextmanager

import anyio
import httpx
from httpx_sse import EventSource
from pydantic import TypeAdapter

import mcp.types as types
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

STREAMABLE_PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    types.LATEST_PROTOCOL_VERSION,
    STREAMABLE_PROTOCOL_VERSION,
)


@asynccontextmanager
async def streamable_client(
    url: str,
    timeout: float = 5,
):
    """
    Client transport for streamable HTTP, with fallback to SSE.
    """
    if await _is_old_sse_server(url, timeout):
        async with sse_client(url) as (read_stream, write_stream):
            yield read_stream, write_stream
        return

    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        types.JSONRPCMessage | Exception
    ](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        types.JSONRPCMessage
    ](0)

    async def handle_response(text: str) -> None:
        items = _maybe_list_adapter.validate_json(text)
        if isinstance(items, types.JSONRPCMessage):
            items = [items]
        for item in items:
            await read_stream_writer.send(item)

    headers: tuple[tuple[str, str], ...] = ()

    async with anyio.create_task_group() as tg:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:

                async def sse_reader(event_source: EventSource):
                    try:
                        async for sse in event_source.aiter_sse():
                            logger.debug(f"Received SSE event: {sse.event}")
                            match sse.event:
                                case "message":
                                    try:
                                        await handle_response(sse.data)
                                        logger.debug(
                                            f"Received server message: {sse.data}"
                                        )
                                    except Exception as exc:
                                        logger.error(
                                            f"Error parsing server message: {exc}"
                                        )
                                        await read_stream_writer.send(exc)
                                        continue
                                case _:
                                    logger.warning(f"Unknown SSE event: {sse.event}")
                    except Exception as exc:
                        logger.error(f"Error in sse_reader: {exc}")
                        await read_stream_writer.send(exc)
                    finally:
                        await read_stream_writer.aclose()

                async def post_writer():
                    nonlocal headers
                    try:
                        async with write_stream_reader:
                            async for message in write_stream_reader:
                                logger.debug(f"Sending client message: {message}")
                                response = await client.post(
                                    url,
                                    json=message.model_dump(
                                        by_alias=True,
                                        mode="json",
                                        exclude_none=True,
                                    ),
                                    headers=(
                                        ("accept", "application/json"),
                                        ("accept", "text/event-stream"),
                                        *headers,
                                    ),
                                )
                                logger.debug(
                                    f"response {url=} content-type={response.headers.get("content-type")} body={response.text}"
                                )

                                response.raise_for_status()
                                match response.headers.get("mcp-session-id"):
                                    case str() as session_id:
                                        headers = (("mcp-session-id", session_id),)
                                    case _:
                                        pass

                                match response.headers.get("content-type"):
                                    case "text/event-stream":
                                        await sse_reader(EventSource(response))
                                    case "application/json":
                                        await handle_response(response.text)
                                    case None:
                                        pass
                                    case unknown:
                                        logger.warning(
                                            f"Unknown content type: {unknown}"
                                        )

                                logger.debug(
                                    "Client message sent successfully: "
                                    f"{response.status_code}"
                                )
                    except Exception as exc:
                        logger.error(f"Error in post_writer: {exc}", exc_info=True)
                    finally:
                        await write_stream.aclose()

                tg.start_soon(post_writer)

                try:
                    yield read_stream, write_stream
                finally:
                    tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()


_maybe_list_adapter: TypeAdapter[types.JSONRPCMessage | list[types.JSONRPCMessage]] = (
    TypeAdapter(types.JSONRPCMessage | list[types.JSONRPCMessage])
)


async def _is_old_sse_server(url: str, timeout: float) -> bool:
    """
    Test whether this is an old SSE MCP server.

    See: https://spec.modelcontextprotocol.io/specification/2025-03-26/basic/transports/#backwards-compatibility
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        test_initialize_request = types.InitializeRequest(
            method="initialize",
            params=types.InitializeRequestParams(
                protocolVersion=STREAMABLE_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(),
                clientInfo=types.Implementation(name="mcp", version="0.1.0"),
            ),
        )
        response = await client.post(
            url,
            json=types.JSONRPCRequest(
                jsonrpc="2.0",
                id=1,
                method=test_initialize_request.method,
                params=test_initialize_request.params.model_dump(
                    by_alias=True, mode="json", exclude_none=True
                ),
            ).model_dump(by_alias=True, mode="json", exclude_none=True),
            headers=(
                ("accept", "application/json"),
                ("accept", "text/event-stream"),
            ),
        )
        if 400 <= response.status_code < 500:
            return True
    return False
