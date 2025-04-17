#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "mcp",
# ]
# [tool.uv.sources]
# mcp = { path = "/workspace" }
# ///

##
## The goal of this example is to demonstrate a workflow where
## users can define their own message types for MCP and how to
## process then client and/or server side.
##
## In this concrete example we demonstrate a new set of message types
## such that the client sends a request to the server and the server
## sends a response back to the client and back and forth until a TTL
## is reached.
##
## This is meant to demonstrate a possible future where MCP is used
## more bidirectionally as defined by a user.
##


import asyncio as aio
from typing import Any, Literal

import anyio

import mcp.types as types
from mcp.client.session import ClientSession, CustomRequestHandlerFnT
from mcp.server.lowlevel import Server
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_client_server_memory_streams

EXPERIMENTAL_CAPABILITIES: dict[str, dict[str, Any]] = {"custom_requests": {}}

## Define the 'awesome' protocol


class AwesomeParams(types.RequestParams):
    ttl: int
    payload: str


class AwesomeRequest(types.CustomRequest[AwesomeParams, Literal["awesome/request"]]):
    method: Literal["awesome/request"] = "awesome/request"
    params: AwesomeParams


class AwesomeResult(types.CustomResult):
    """
    A response to a Awesome request.
    """

    payload: str


async def run_all():
    async with anyio.create_task_group() as tg:
        async with create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            ## MCP Server code
            server = Server("my-custom-server")

            @server.handle_custom_request(AwesomeRequest)
            async def handle_awesome_request(req: AwesomeRequest) -> AwesomeResult:
                print(f"SERVER: RECEIVED REQUEST WITH TTL={req.params.ttl}")
                if req.params.ttl > 0:
                    tg.start_soon(
                        server.request_context.session.send_custom_request,
                        AwesomeRequest(
                            params=AwesomeParams(
                                ttl=req.params.ttl - 1, payload=req.params.payload
                            )
                        ),
                        AwesomeResult,
                    )
                return AwesomeResult(payload="woohoo!")

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

            ## MCP Client code

            class AwesomeResponder(CustomRequestHandlerFnT[AwesomeRequest]):
                async def __call__(
                    self,
                    context: RequestContext["ClientSession", Any],
                    message: AwesomeRequest,
                ) -> types.ClientResult | types.ErrorData:
                    print(f"CLIENT: RECEIVED REQUEST WITH TTL={message.params.ttl}")
                    if message.params.ttl > 0:
                        tg.start_soon(
                            context.session.send_custom_request,
                            AwesomeRequest(
                                params=AwesomeParams(
                                    ttl=message.params.ttl - 1,
                                    payload=message.params.payload,
                                )
                            ),
                            AwesomeResult,
                        )
                    return types.ClientResult(AwesomeResult(payload="woohoo!"))

            async with ClientSession(
                read_stream=client_read,
                write_stream=client_write,
                experimental_capabilities=EXPERIMENTAL_CAPABILITIES,
                custom_request_handlers={
                    "awesome/request": AwesomeResponder(),
                },
            ) as client_session:
                await client_session.initialize()

                req = AwesomeRequest(params=AwesomeParams(ttl=10, payload="hooray!"))
                print(f"Sending: {req}")
                await client_session.send_custom_request(
                    req, response_type=AwesomeResult
                )
                await anyio.sleep(1)

            tg.cancel_scope.cancel()


if __name__ == "__main__":
    aio.run(run_all())
