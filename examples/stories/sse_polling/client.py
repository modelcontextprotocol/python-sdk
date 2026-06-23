"""Call a tool whose SSE stream the server closes mid-flight; assert the call still completes."""

import anyio

from mcp.client import Client
from mcp.types import TextContent
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    messages: list[str | None] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        messages.append(message)

    with anyio.fail_after(10):
        result = await client.call_tool("long_operation", {}, progress_callback=on_progress)

    # The result arrived — the client transport survived the server-initiated close,
    # reconnected with Last-Event-ID, and received the replayed response.
    assert not result.is_error, result
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "resumed"

    # "after-close" was emitted while no SSE stream was open; receiving it proves the
    # event store buffered it and the reconnect replayed it.
    assert messages == ["before-close", "after-close"], messages


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
