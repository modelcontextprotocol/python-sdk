"""Exercise an installed client distribution without the SDK's server dependencies.

The peer uses raw messages because the server package must be absent from this environment.
"""

import importlib
import importlib.util
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import get_type_hints

import anyio
import mcp_client
from mcp_client.shared.memory import MessageStream, create_client_server_memory_streams
from mcp_client.shared.message import SessionMessage
from mcp_types import JSONRPCRequest, JSONRPCResponse, ListToolsResult, Tool

get_type_hints(mcp_client.Client.__init__)

for name in ("mcp", "starlette", "uvicorn", "sse_starlette", "multipart"):
    assert importlib.util.find_spec(name) is None, name

for info in pkgutil.walk_packages(mcp_client.__path__, prefix="mcp_client."):
    if not any(part.startswith("_") for part in info.name.split(".")):
        importlib.import_module(info.name)

RESULT = ListToolsResult(tools=[Tool(name="example", input_schema={"type": "object"})])


@asynccontextmanager
async def transport() -> AsyncIterator[MessageStream]:
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        read, write = server_streams

        async def respond() -> None:
            received = await read.receive()
            assert isinstance(received, SessionMessage)
            message = received.message
            assert isinstance(message, JSONRPCRequest)
            assert message.method == "tools/list"
            await write.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0", id=message.id, result=RESULT.model_dump(by_alias=True, exclude_none=True)
                    )
                )
            )

        async with anyio.create_task_group() as group:
            group.start_soon(respond)
            yield client_streams


async def main() -> None:
    """Verify a client request and response through the installed public API."""
    with anyio.fail_after(5):
        async with mcp_client.Client(transport(), mode="2026-07-28") as client:
            assert await client.list_tools() == RESULT


anyio.run(main)
