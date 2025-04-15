#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "mcp",
# ]
# [tool.uv.sources]
# mcp = { path = "/workspace" }
# ///

from typing import Literal
import anyio
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.server.lowlevel import Server
import sys
from mcp.server.stdio import stdio_server
import asyncio as aio
from mcp.shared.context import RequestContext
from pydantic import RootModel, BaseModel, ConfigDict, Field
from typing import Any, TypeVar
from mcp.client.session import ExperimentalMessageHandlerFnT
from mcp.server.session import ServerSession


EXPERIMENTAL_CAPABILITIES = {
    "my-awesome-capability": {
        "delay": 1000,
    }
}


## My awesome capability messages
class AwesomeParams(types.RequestParams):
    payload: str


class AwesomeRequest(
    types.ExperimentalRequest[AwesomeParams, Literal["experimental/awesome"]]
):
    method: Literal["experimental/awesome"] = "experimental/awesome"
    params: AwesomeParams


class AwesomeResponse(types.ExperimentalResult):
    """
    A response to a Awesome request.
    """

    payload: str


## MCP Server code
server = Server("my-custom-server")


@server.handle_experimental_request(AwesomeRequest)
async def handle_awesome_request(req: AwesomeRequest) -> AwesomeResponse:
    return AwesomeResponse(payload="wow!")


async def run_all():
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(
                        experimental_capabilities=EXPERIMENTAL_CAPABILITIES,
                    ),
                    raise_exceptions=True,
                )
            )

            try:

                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    experimental_capabilities=EXPERIMENTAL_CAPABILITIES,
                ) as client_session:
                    await client_session.initialize()

                    req = AwesomeRequest(params=AwesomeParams(payload="hooray!"))
                    print(f"Sending: {req}")
                    res = await client_session.send_experimental_request(
                        req, response_type=AwesomeResponse
                    )
                    print(f"Received: {res}")
            finally:
                tg.cancel_scope.cancel()


if __name__ == "__main__":
    aio.run(run_all())
