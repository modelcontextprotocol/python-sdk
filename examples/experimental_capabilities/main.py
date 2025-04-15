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
from mcp.client.session import ClientSession, ExperimentalMessageHandlerFnT
from mcp.server.lowlevel import Server
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_client_server_memory_streams

EXPERIMENTAL_CAPABILITIES = {
    "my-awesome-capability": {
        "delay": 1000,
    }
}

## Define the 'awesome' protocol


class AwesomeParams(types.RequestParams):
    ttl: int
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


async def run_all():
    async with anyio.create_task_group() as background_tg:
        # Add this to share the task group
        global BACKGROUND_TG
        BACKGROUND_TG = background_tg

        async with create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            ## MCP Server code
            server = Server("my-custom-server")

            @server.handle_experimental_request(AwesomeRequest)
            async def handle_awesome_request(req: AwesomeRequest) -> AwesomeResponse:
                await anyio.lowlevel.checkpoint()
                print(f"SERVER: RECEIVED REQUEST WITH TTL={req.params.ttl}")
                session = server.request_context.session
                if req.params.ttl > 0:
                    BACKGROUND_TG.start_soon(
                        session.send_experimental_request,
                        AwesomeRequest(
                            params=AwesomeParams(
                                ttl=req.params.ttl - 1, payload=req.params.payload
                            )
                        ),
                        AwesomeResponse,
                    )
                return AwesomeResponse(payload="woohoo!")

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

                    class AwesomeResponder(ExperimentalMessageHandlerFnT):
                        async def __call__(
                            self,
                            context: RequestContext["ClientSession", Any],
                            params: dict[str, Any] | None,
                        ) -> types.ExperimentalResult | types.ErrorData:
                            print(f"CLIENT: RECEIVED REQUEST WITH TTL={params['ttl']}")
                            await anyio.lowlevel.checkpoint()
                            session = context.session
                            if params["ttl"] > 0:
                                BACKGROUND_TG.start_soon(
                                    session.send_experimental_request,
                                    AwesomeRequest(
                                        params=AwesomeParams(
                                            ttl=params["ttl"] - 1,
                                            payload=params["payload"],
                                        )
                                    ),
                                    AwesomeResponse,
                                )
                            return AwesomeResponse(payload="woohoo!")

                    async with ClientSession(
                        read_stream=client_read,
                        write_stream=client_write,
                        experimental_capabilities=EXPERIMENTAL_CAPABILITIES,
                        experimental_capabilities_callbacks={
                            "awesome": AwesomeResponder(),
                        },
                    ) as client_session:
                        await client_session.initialize()

                        req = AwesomeRequest(
                            params=AwesomeParams(ttl=10, payload="hooray!")
                        )
                        print(f"Sending: {req}")
                        res = await client_session.send_experimental_request(
                            req, response_type=AwesomeResponse
                        )
                        print(f"Received: {res}")
                        await anyio.sleep(1)
                finally:
                    tg.cancel_scope.cancel()


if __name__ == "__main__":
    aio.run(run_all())
