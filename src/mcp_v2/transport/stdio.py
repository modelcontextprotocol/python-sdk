"""MCP V2 Stdio Transport - Run a LowLevelServer over stdin/stdout."""

from __future__ import annotations

import sys

import anyio
import anyio.abc

from mcp_v2.runner import Lifespan, ServerRunner
from mcp_v2.server import LowLevelServer
from mcp_v2.transport.sink import ChannelSink, SinkEvent
from mcp_v2.types.json_rpc import JSONRPCMessageAdapter, JSONRPCNotification


async def run_stdio(server: LowLevelServer, *, lifespan: Lifespan | None = None) -> None:
    """Run a LowLevelServer over stdin/stdout (newline-delimited JSON-RPC)."""
    runner = ServerRunner(server, lifespan=lifespan)
    async with runner.run() as running:
        stdin = anyio.wrap_file(sys.stdin)
        async for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            message = JSONRPCMessageAdapter.validate_json(line)

            # Notifications don't produce responses
            if isinstance(message, JSONRPCNotification):
                send, recv = anyio.create_memory_object_stream[SinkEvent](16)
                sink = ChannelSink(send)
                await running.handle_message(sink, message)
                async with recv:
                    pass
                continue

            # Requests: collect all sink events and write to stdout
            send, recv = anyio.create_memory_object_stream[SinkEvent](16)
            sink = ChannelSink(send)
            await running.handle_message(sink, message)
            async with recv:
                async for event in recv:
                    data = event.message.model_dump_json(by_alias=True, exclude_none=True)
                    sys.stdout.write(data + "\n")
                    sys.stdout.flush()
