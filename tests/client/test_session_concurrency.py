"""Concurrency over a single client session: multiple requests in flight at once, in both directions."""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import (
    CallToolResult,
    CreateMessageRequestParams,  # pyright: ignore[reportDeprecated]
    CreateMessageResult,  # pyright: ignore[reportDeprecated]
    SamplingMessage,  # pyright: ignore[reportDeprecated]
    TextContent,
)

pytestmark = pytest.mark.anyio


async def test_concurrent_tool_calls_resolve_out_of_order_to_their_own_callers() -> None:
    """Three tool calls in flight at once on one session each receive their own result, even though
    the responses come back in the reverse of the order the requests were sent.

    SDK-defined contract: pins the client request machinery's support for concurrent in-flight
    calls with out-of-order response correlation. Each handler parks on its own release event
    after signalling it started; a session that serialized requests would never start the later
    handlers and the test would time out instead.
    """
    send_order = ["a", "b", "c"]
    started = {tag: anyio.Event() for tag in send_order}
    release = {tag: anyio.Event() for tag in send_order}
    done = {tag: anyio.Event() for tag in send_order}
    completion_order: list[str] = []
    results: dict[str, CallToolResult] = {}

    server = MCPServer("parking")

    @server.tool()
    async def park(tag: str) -> str:
        started[tag].set()
        await release[tag].wait()
        return f"result:{tag}"

    async with Client(server) as client:

        async def call_and_record(tag: str) -> None:
            results[tag] = await client.call_tool("park", {"tag": tag})
            completion_order.append(tag)
            done[tag].set()

        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:  # pragma: no branch
                # Waiting for each handler to start before issuing the next call fixes the send
                # order, and leaves all three parked in flight together once the loop finishes.
                for tag in send_order:
                    task_group.start_soon(call_and_record, tag)
                    await started[tag].wait()

                # Nothing completed yet: all three calls are genuinely concurrent.
                assert completion_order == []

                # Release in reverse, awaiting each completion so the finish order is forced.
                for tag in reversed(send_order):
                    release[tag].set()
                    await done[tag].wait()

    assert completion_order == ["c", "b", "a"]
    assert results == snapshot(
        {
            "c": CallToolResult(content=[TextContent(text="result:c")], structured_content={"result": "result:c"}),
            "b": CallToolResult(content=[TextContent(text="result:b")], structured_content={"result": "result:b"}),
            "a": CallToolResult(content=[TextContent(text="result:a")], structured_content={"result": "result:a"}),
        }
    )


async def test_overlapping_sampling_requests_are_serviced_concurrently_by_the_client() -> None:
    """A server tool that fans out two sampling requests at once gets both echoes back: the client
    runs overlapping inbound `create_message` requests concurrently instead of serializing them in
    its receive loop.

    Regression pin for https://github.com/modelcontextprotocol/python-sdk/issues/2489 -- v1's
    `BaseSession` awaited each inbound request handler inline, so the second sampling callback
    could not start until the first returned; here both rendezvous before either is released.
    """
    sampling_started = {"x": anyio.Event(), "y": anyio.Event()}
    sampling_release = anyio.Event()
    tool_results: list[CallToolResult] = []

    server = MCPServer("fan_out_server")

    @server.tool()
    async def fan_out(ctx: Context) -> str:
        echoes: dict[str, str] = {}

        async def sample(tag: str) -> None:
            result = await ctx.session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(text=tag))],  # pyright: ignore[reportDeprecated]
                max_tokens=10,
            )
            assert isinstance(result.content, TextContent)
            echoes[tag] = result.content.text

        async with anyio.create_task_group() as sampler_group:
            sampler_group.start_soon(sample, "x")
            sampler_group.start_soon(sample, "y")
        return f"{echoes['x']} {echoes['y']}"

    async def sampling_callback(
        context: ClientRequestContext,
        params: CreateMessageRequestParams,  # pyright: ignore[reportDeprecated]
    ) -> CreateMessageResult:  # pyright: ignore[reportDeprecated]
        content = params.messages[0].content
        assert isinstance(content, TextContent)
        sampling_started[content.text].set()
        await sampling_release.wait()
        return CreateMessageResult(  # pyright: ignore[reportDeprecated]
            role="assistant",
            content=TextContent(text=f"echo:{content.text}"),
            model="test-model",
            stop_reason="endTurn",
        )

    async with Client(server, sampling_callback=sampling_callback) as client:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as task_group:  # pragma: no branch

                async def invoke_fan_out() -> None:
                    tool_results.append(await client.call_tool("fan_out", {}))

                task_group.start_soon(invoke_fan_out)

                # Both sampling callbacks are mid-flight before either may answer -- a client that
                # serialized inbound requests would never start the second one.
                await sampling_started["x"].wait()
                await sampling_started["y"].wait()
                sampling_release.set()

    assert tool_results == snapshot(
        [CallToolResult(content=[TextContent(text="echo:x echo:y")], structured_content={"result": "echo:x echo:y"})]
    )
